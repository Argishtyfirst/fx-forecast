import { AxisRight } from "@visx/axis";
import { curveLinear } from "@visx/curve";
import { Group } from "@visx/group";
import { scaleLinear } from "@visx/scale";
import { LinePath } from "@visx/shape";
import { useId, useMemo, useState } from "react";
import type { BandKey, HorizonForecast, LatestForecastResponse, RatePoint } from "../api/types";
import { BAND_KEYS, BANK_LABELS, DISCLAIMER } from "../lib/constants";
import {
  assignLanes,
  bandPolygon,
  fanVertices,
  placeMeetings,
  yDomain,
  type FanVertex,
} from "../lib/fan";
import { fmtDate, fmtMonth, fmtRange, fmtRate, fmtShortDate } from "../lib/format";
import { useWidth } from "../lib/useWidth";

export interface FanChartProps {
  pairLabel: string;
  decimals: number;
  /** History window, oldest first, ending at the spot date (90 trading days). */
  history: RatePoint[];
  forecast: LatestForecastResponse | null;
  /** Fixed width for tests; otherwise the chart fills its container. */
  width?: number;
}

const MARGIN = { left: 4, right: 58, bottom: 26 };
const REGION_ROW = 18;
const LANE_H = 15;
const CHAR_W = 6.4; // Geist Mono at 10.5px

type Target =
  | { kind: "history"; index: number; x: number; y: number; point: RatePoint }
  | { kind: "horizon"; x: number; y: number; vertex: FanVertex };

export function FanChart({ pairLabel, decimals, history, forecast, width: fixedWidth }: FanChartProps) {
  const [ref, measured] = useWidth<HTMLDivElement>(fixedWidth ?? 800);
  const width = fixedWidth ?? measured;
  const [active, setActive] = useState<number | null>(null);
  const readoutId = useId();

  const narrow = width < 560;
  const height = narrow ? 270 : 340;

  const vertices = useMemo(
    () => (forecast ? fanVertices(forecast.spot, forecast.spot_date, forecast.horizons) : []),
    [forecast],
  );
  const meetings = useMemo(
    () => (forecast ? placeMeetings(forecast.horizons, vertices) : []),
    [forecast, vertices],
  );

  const innerW = Math.max(width - MARGIN.left - MARGIN.right, 10);
  const tMin = -(Math.max(history.length, 1) - 1);
  const tMax = vertices.length > 1 ? vertices[vertices.length - 1].t : 0;
  const split = tMax > 0 ? innerW * (narrow ? 0.52 : 0.62) : innerW;
  const x = (t: number) =>
    t <= 0
      ? tMin === 0
        ? split
        : (split * (t - tMin)) / (0 - tMin)
      : split + ((innerW - split) * t) / tMax;

  // Meeting labels: short on narrow screens, laid out in lanes so neighbours never overlap.
  const meetingLabels = meetings.map((m) =>
    narrow ? BANK_LABELS[m.bank] ?? m.bank : `${BANK_LABELS[m.bank] ?? m.bank} ${fmtShortDate(m.date)}`,
  );
  const lanes = assignLanes(
    meetings.map((m, i) => ({ x: x(m.t), width: meetingLabels[i].length * CHAR_W + 6 })),
    6,
  );
  const laneCount = meetings.length ? Math.max(...lanes) + 1 : 0;
  const top = REGION_ROW + laneCount * LANE_H + 8;
  const innerH = height - top - MARGIN.bottom;

  const [y0, y1] = yDomain(history, vertices);
  const y = useMemo(
    () => scaleLinear<number>({ domain: [y0, y1], range: [innerH, 0], nice: false }),
    [y0, y1, innerH],
  );
  const yTicks = y.ticks(narrow ? 4 : 5);
  const tickFormat = y.tickFormat(narrow ? 4 : 5);

  // Hover and keyboard targets: every history day, then the three horizon points.
  const targets: Target[] = useMemo(() => {
    const hist: Target[] = history.map((point, index) => {
      const t = index - (history.length - 1);
      return { kind: "history", index, x: x(t), y: y(point.rate), point };
    });
    const hor: Target[] = vertices
      .slice(1)
      .map((vertex) => ({ kind: "horizon", x: x(vertex.t), y: y(vertex.center), vertex }));
    return [...hist, ...hor];
  }, [history, vertices, y, innerW, split, tMin, tMax]);

  const activeTarget = active !== null ? targets[active] : null;

  const onPointer = (e: React.PointerEvent<SVGRectElement>) => {
    const rect = e.currentTarget.getBoundingClientRect();
    const px = e.clientX - rect.left;
    let best = 0;
    let bestD = Infinity;
    targets.forEach((tg, i) => {
      const d = Math.abs(tg.x - px);
      if (d < bestD) {
        bestD = d;
        best = i;
      }
    });
    setActive(best);
  };

  const onKey = (e: React.KeyboardEvent<HTMLDivElement>) => {
    if (!targets.length) return;
    const last = targets.length - 1;
    const cur = active ?? last - (vertices.length > 1 ? vertices.length - 1 : 0);
    let next: number | null = null;
    if (e.key === "ArrowLeft") next = Math.max(0, cur - 1);
    else if (e.key === "ArrowRight") next = Math.min(last, cur + 1);
    else if (e.key === "Home") next = 0;
    else if (e.key === "End") next = last;
    else if (e.key === "Escape") next = null;
    else return;
    e.preventDefault();
    setActive(next);
  };

  // X-axis labels, placed by priority; a label that would collide with a placed one is dropped.
  const xLabels = useMemo(() => {
    const placed: { x: number; text: string; anchor: "start" | "middle" | "end"; strong?: boolean }[] = [];
    const boxes: [number, number][] = [];
    const tryPlace = (px: number, text: string, anchor: "start" | "middle" | "end", strong = false, gap = 8) => {
      const w = text.length * CHAR_W;
      const x0 = anchor === "start" ? px : anchor === "end" ? px - w : px - w / 2;
      const x1 = x0 + w;
      if (x0 < -MARGIN.left || x1 > innerW + MARGIN.right) return;
      if (boxes.some(([a, b]) => x0 < b + gap && x1 > a - gap)) return;
      boxes.push([x0, x1]);
      placed.push({ x: px, text, anchor, strong });
    };
    for (const v of [...vertices.slice(1)].reverse()) {
      const px = x(v.t);
      // A horizon close to the spot rule starts at its point instead of centring on it.
      const anchor = v.t === tMax ? "end" : px - split < 14 ? "start" : "middle";
      tryPlace(anchor === "start" ? px - 3 : px, v.label ?? "", anchor, true, 4);
    }
    // The spot date yields to the horizon labels on narrow screens; the readout carries it too.
    if (forecast && history.length) tryPlace(split - 4, fmtShortDate(forecast.spot_date), "end", true);
    // First trading day of each month in the history window.
    history.forEach((p, i) => {
      if (i === 0) return;
      if (p.date.slice(0, 7) !== history[i - 1].date.slice(0, 7)) {
        tryPlace(x(i - (history.length - 1)), fmtMonth(p.date), "start");
      }
    });
    return placed;
  }, [history, vertices, forecast, innerW, split]);

  const summary = useMemo(
    () => buildSummary(pairLabel, decimals, history, forecast, meetings.map((m) => `${BANK_LABELS[m.bank] ?? m.bank} ${fmtDate(m.date)}`)),
    [pairLabel, decimals, history, forecast, meetings],
  );

  const spotT = 0;
  const lastHistory = history[history.length - 1];

  return (
    <div className="fan">
      <Readout
        id={readoutId}
        target={activeTarget}
        decimals={decimals}
        forecast={forecast}
        lastHistory={lastHistory}
      />
      <div
        ref={ref}
        className="fan-frame"
        tabIndex={0}
        aria-describedby={readoutId}
        aria-label={`${pairLabel} fan chart. Use the arrow keys to read values.`}
        onKeyDown={onKey}
        onBlur={() => setActive(null)}
      >
        {width > 0 && (
          <svg
            className="fan-svg"
            width={width}
            height={height}
            role="img"
            aria-label={summary}
            data-testid="fan-chart"
          >
            <Group left={MARGIN.left} top={top}>
              {tMax > 0 && (
                <rect
                  className="fan-forecast-bg"
                  x={split}
                  y={-top + REGION_ROW - 4}
                  width={innerW - split}
                  height={innerH + top - REGION_ROW + 4}
                />
              )}

              {/* Region labels */}
              <text className="fan-region" x={0} y={-top + 12}>
                {narrow ? "History" : `History · ${history.length} trading days`}
              </text>
              {tMax > 0 && (
                <text className="fan-region" x={split + 8} y={-top + 12}>
                  {narrow ? "Forecast" : `Forecast · ${tMax} trading days`}
                </text>
              )}

              {/* Gridlines */}
              <g className="fan-grid">
                {yTicks.map((tv) => (
                  <line key={tv} x1={0} x2={innerW} y1={y(tv)} y2={y(tv)} />
                ))}
              </g>

              {/* Meeting markers: a rule through the plot, a tick and the bank label above it */}
              <g className="fan-meetings">
                {meetings.map((m, i) => {
                  const mx = x(m.t);
                  const ly = -top + REGION_ROW + lanes[i] * LANE_H + 10;
                  return (
                    <g
                      key={`${m.bank}-${m.date}`}
                      data-testid="meeting-marker"
                      data-bank={m.bank}
                      data-date={m.date}
                    >
                      <line className="fan-meeting-rule" x1={mx} x2={mx} y1={ly + 3} y2={innerH} />
                      <line className="fan-meeting-tick" x1={mx} x2={mx} y1={ly - 9} y2={ly + 3} />
                      <text className="fan-meeting-label" x={mx + 4} y={ly}>
                        {meetingLabels[i]}
                      </text>
                    </g>
                  );
                })}
              </g>

              {/* Bands, widest first so the 50% band sits on top */}
              <g className="fan-bands">
                {vertices.length > 1 &&
                  BAND_KEYS.map((k) => (
                    <path
                      key={k}
                      className={`fan-band fan-band-${k}`}
                      data-band={k}
                      data-horizons={vertices
                        .slice(1)
                        .map((v) => v.label)
                        .join(" ")}
                      d={polygonPath(bandPolygon(vertices, k), x, y)}
                    />
                  ))}
              </g>

              {tMax > 0 && (
                <line className="fan-spot-rule" x1={split} x2={split} y1={-6} y2={innerH} />
              )}

              {/* History */}
              {history.length > 1 && (
                <LinePath
                  className="fan-history"
                  data-testid="history-line"
                  data-points={history.length}
                  data={history}
                  x={(_, i) => x(i - (history.length - 1))}
                  y={(d) => y(d.rate)}
                  curve={curveLinear}
                />
              )}

              {/* Center: subtle, the bands carry the message */}
              {vertices.length > 1 && (
                <LinePath
                  className="fan-center"
                  data-testid="center-line"
                  data={vertices}
                  x={(v) => x(v.t)}
                  y={(v) => y(v.center)}
                  curve={curveLinear}
                />
              )}
              {vertices.slice(1).map((v) => (
                <circle
                  key={v.t}
                  className="fan-horizon-dot"
                  data-horizon-point={v.label ?? ""}
                  cx={x(v.t)}
                  cy={y(v.center)}
                  r={3.5}
                />
              ))}
              {lastHistory && (
                <circle className="fan-spot-dot" cx={x(spotT)} cy={y(lastHistory.rate)} r={3.5} />
              )}

              {/* Y axis on the right, next to the fan */}
              <AxisRight
                left={innerW}
                scale={y}
                tickValues={yTicks}
                tickFormat={(v) => tickFormat(v as number)}
                hideAxisLine
                hideTicks
                tickLabelProps={() => ({
                  className: "fan-tick",
                  dx: 10,
                  dy: "0.32em",
                  textAnchor: "start",
                })}
              />

              {/* X labels */}
              <g className="fan-xaxis">
                <line className="fan-baseline" x1={0} x2={innerW} y1={innerH} y2={innerH} />
                {xLabels.map((l) => (
                  <text
                    key={`${l.text}-${l.x}`}
                    className={l.strong ? "fan-tick fan-tick-strong" : "fan-tick"}
                    x={l.x}
                    y={innerH + 17}
                    textAnchor={l.anchor}
                  >
                    {l.text}
                  </text>
                ))}
              </g>

              {/* Hover layer */}
              {activeTarget && (
                <g className="fan-hover" pointerEvents="none">
                  <line x1={activeTarget.x} x2={activeTarget.x} y1={0} y2={innerH} />
                  {activeTarget.kind === "horizon" && (
                    <>
                      {(["95", "80", "50"] as BandKey[]).map((k) => (
                        <line
                          key={k}
                          className={`fan-hover-band fan-hover-band-${k}`}
                          x1={activeTarget.x}
                          x2={activeTarget.x}
                          y1={y(activeTarget.vertex.bands[k][0])}
                          y2={y(activeTarget.vertex.bands[k][1])}
                        />
                      ))}
                    </>
                  )}
                  <circle cx={activeTarget.x} cy={activeTarget.y} r={4.5} />
                </g>
              )}
              <rect
                className="fan-overlay"
                x={0}
                y={0}
                width={innerW}
                height={innerH}
                onPointerMove={onPointer}
                onPointerDown={onPointer}
                onPointerLeave={() => setActive(null)}
              />
            </Group>
          </svg>
        )}
      </div>
    </div>
  );
}

function polygonPath(points: [number, number][], x: (t: number) => number, y: (v: number) => number) {
  return (
    points
      .map(([t, v], i) => `${i === 0 ? "M" : "L"}${x(t).toFixed(2)},${y(v).toFixed(2)}`)
      .join("") + "Z"
  );
}

function Readout({
  id,
  target,
  decimals,
  forecast,
  lastHistory,
}: {
  id: string;
  target: Target | null;
  decimals: number;
  forecast: LatestForecastResponse | null;
  lastHistory: RatePoint | undefined;
}) {
  let content: React.ReactNode;
  if (target?.kind === "history") {
    content = (
      <>
        <span className="readout-key">{fmtDate(target.point.date)}</span>
        <span className="readout-value num">{fmtRate(target.point.rate, decimals)}</span>
      </>
    );
  } else if (target?.kind === "horizon") {
    const v = target.vertex;
    content = (
      <>
        <span className="readout-key">
          {v.label} &middot; {fmtDate(v.date)}
        </span>
        <span className="readout-item">
          <span className="readout-label">80%</span>
          <span className="readout-value num">{fmtRange(v.bands["80"][0], v.bands["80"][1], decimals)}</span>
        </span>
        <span className="readout-item">
          <span className="readout-label">50%</span>
          <span className="num">{fmtRange(v.bands["50"][0], v.bands["50"][1], decimals)}</span>
        </span>
        <span className="readout-item">
          <span className="readout-label">95%</span>
          <span className="num">{fmtRange(v.bands["95"][0], v.bands["95"][1], decimals)}</span>
        </span>
        <span className="readout-item readout-muted">
          <span className="readout-label">center</span>
          <span className="num">{fmtRate(v.center, decimals)}</span>
        </span>
      </>
    );
  } else if (lastHistory) {
    content = (
      <>
        <span className="readout-key">
          {forecast ? "Spot" : "Last rate"} &middot; {fmtDate(lastHistory.date)}
        </span>
        <span className="readout-value num">{fmtRate(lastHistory.rate, decimals)}</span>
        <span className="readout-hint">Hover or use the arrow keys to read a day or a horizon.</span>
      </>
    );
  } else {
    content = <span className="readout-hint">No rate history yet.</span>;
  }
  return (
    <div id={id} className="fan-readout" aria-live="polite">
      {content}
    </div>
  );
}

function buildSummary(
  pairLabel: string,
  decimals: number,
  history: RatePoint[],
  forecast: LatestForecastResponse | null,
  meetings: string[],
): string {
  const parts: string[] = [`${pairLabel} fan chart.`];
  if (history.length) {
    const first = history[0];
    const last = history[history.length - 1];
    parts.push(
      `${history.length} trading days of history from ${fmtDate(first.date)} to ${fmtDate(last.date)}, last ${fmtRate(last.rate, decimals)}.`,
    );
  }
  if (forecast) {
    const ranges = [...forecast.horizons]
      .sort((a, b) => a.days - b.days)
      .map((h: HorizonForecast) => {
        const b = h.bands["80"];
        return b ? `${h.label} to ${fmtDate(h.target_date)}: ${fmtRange(b[0], b[1], decimals)}` : `${h.label}: no band`;
      });
    parts.push(`80% ranges: ${ranges.join("; ")}.`);
    parts.push(
      meetings.length ? `Central bank meetings inside the horizons: ${meetings.join(", ")}.` : "No central bank meetings inside the horizons.",
    );
    parts.push(forecast.disclaimer || DISCLAIMER);
  } else {
    parts.push("No forecast yet.");
  }
  return parts.join(" ");
}
