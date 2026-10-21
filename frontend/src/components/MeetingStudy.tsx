import { curveMonotoneX } from "@visx/curve";
import { scaleLinear } from "@visx/scale";
import { LinePath } from "@visx/shape";
import { useId, useMemo, useState } from "react";
import type { BankReactionSummaryOut, MeetingReactionOut, MeetingStudyResponse, PathPoint } from "../api/types";
import { BANK_LABELS, BANKS, DISCLAIMER } from "../lib/constants";
import { fmtDate, fmtNum, fmtShortDate } from "../lib/format";
import { useWidth } from "../lib/useWidth";

interface MeetingStudyProps {
  study: MeetingStudyResponse;
  pairLabel: string;
  /** Bank picked in the Events filter; it gets the accent, the others stay grey. */
  focusBank?: string;
}

export const pctS = (x: number | null | undefined, digits = 2) => {
  if (x === null || x === undefined || !Number.isFinite(x)) return "n/a";
  const r = Number(x.toFixed(digits));
  if (r === 0) return `${(0).toFixed(digits)}%`;
  return `${r > 0 ? "+" : "−"}${Math.abs(r).toFixed(digits)}%`;
};

export function ratioWord(r: number): string {
  return r >= 2 ? `about ${Math.round(r)}×` : `about ${r.toFixed(1)}×`;
}

/** The plain-language takeaway for one bank. */
export function bankTakeaway(b: BankReactionSummaryOut, pairLabel: string, meetings: MeetingReactionOut[]): string {
  const name = BANK_LABELS[b.bank] ?? b.bank;
  const parts: string[] = [];
  if (b.mean_abs_reaction_pct !== null && b.reaction_ratio !== null) {
    parts.push(
      `${name} meetings: ${pairLabel} moved ${fmtNum(b.mean_abs_reaction_pct, 2)}% on average, ${ratioWord(b.reaction_ratio)} a normal day`,
    );
  } else {
    parts.push(`${name} meetings: not enough fixes to measure the move`);
  }
  const noView = meetings.filter((m) => m.bank === b.bank).every((m) => m.expected_sign === 0);
  if (noView) parts.push("no expected direction");
  else if (b.n_signed > 0 && b.consistency !== null)
    parts.push(`followed the surprise or tone ${Math.round(b.consistency * b.n_signed)} of ${b.n_signed} times`);
  else parts.push("no clear signal to follow");
  let text = parts.join(", ");
  if (b.n < 10) text += ` (small sample, ${b.n} meetings)`;
  return `${text}.`;
}

export function toneWord(score: number | null): string {
  if (score === null) return "not scored";
  if (score <= -0.15) return "dovish";
  if (score >= 0.15) return "hawkish";
  return "neutral";
}

function followedWord(m: MeetingReactionOut): string {
  if (m.followed === null) return m.expected_sign === 0 ? "no expected direction" : "no signal";
  return m.followed ? "yes" : "no";
}

const M = { top: 22, right: 48, bottom: 30, left: 6 };
const READ_AT = [-5, 1, 5, 10];

const pctAt = (m: MeetingReactionOut, k: number) => m.path?.find((p) => p.offset === k)?.pct ?? null;

/**
 * Meeting reaction study as an event-study chart: every meeting's path from 10 trading days
 * before the decision to 10 after, measured against the last fix before the decision. The
 * highlighted bank's lines carry the accent over a soft envelope of its typical distance.
 */
export function MeetingStudy({ study, pairLabel, focusBank }: MeetingStudyProps) {
  const [ref, width] = useWidth<HTMLDivElement>(720);
  const banks = BANKS.filter((b) => study.banks.some((s) => s.bank === b));
  const [picked, setPicked] = useState<string | null>(null);
  const highlight = focusBank && banks.includes(focusBank as (typeof banks)[number]) ? focusBank : (picked ?? banks[0]);
  const [activeKey, setActiveKey] = useState<string | null>(null);
  const readoutId = useId();
  const days = study.path_days ?? 10;

  const withPath = useMemo(() => study.meetings.filter((m) => (m.path?.length ?? 0) > 1), [study.meetings]);
  const visible = withPath.filter((m) => !focusBank || m.bank === focusBank);
  const ordered = [...visible].sort((a, b) => (a.bank === highlight ? 1 : 0) - (b.bank === highlight ? 1 : 0) || a.date.localeCompare(b.date));
  const keyOf = (m: MeetingReactionOut) => `${m.bank}|${m.date}`;
  const active = withPath.find((m) => keyOf(m) === activeKey) ?? null;
  const hlMeetings = withPath.filter((m) => m.bank === highlight).sort((a, b) => b.date.localeCompare(a.date));
  const envelope = study.banks.find((b) => b.bank === highlight)?.typical_path ?? [];

  const narrow = width < 480;
  const height = narrow ? 240 : 280;
  const innerW = Math.max(width - M.left - M.right, 10);
  const innerH = height - M.top - M.bottom;
  const x = scaleLinear<number>({ domain: [-days, days], range: [0, innerW] });
  const values = visible.flatMap((m) => (m.path ?? []).map((p) => p.pct));
  const ext = Math.max(0.3, ...values.map(Math.abs), ...envelope.map((e) => e.mean_abs_pct)) * 1.1;
  const y = scaleLinear<number>({ domain: [-ext, ext], range: [innerH, 0], nice: true });
  const yTicks = y.ticks(narrow ? 4 : 5);
  const decisionX = x(0.5);
  const bankName = (b: string) => BANK_LABELS[b] ?? b;

  const onPointer = (e: React.PointerEvent<SVGRectElement>) => {
    const r = e.currentTarget.getBoundingClientRect();
    const px = e.clientX - r.left;
    const py = e.clientY - r.top;
    const k = Math.round(x.invert(px));
    let best: MeetingReactionOut | null = null;
    let bestD = Infinity;
    for (const m of visible) {
      const v = pctAt(m, k);
      if (v === null) continue;
      const d = Math.abs(y(v) - py) + (m.bank === highlight ? 0 : 6);
      if (d < bestD) {
        bestD = d;
        best = m;
      }
    }
    setActiveKey(best && bestD < 40 ? keyOf(best) : null);
  };
  const onKey = (e: React.KeyboardEvent<HTMLDivElement>) => {
    const list = [...hlMeetings].reverse();
    if (!list.length) return;
    const cur = active ? list.findIndex((m) => keyOf(m) === keyOf(active)) : -1;
    let next: number | null | undefined;
    if (e.key === "ArrowRight" || e.key === "ArrowDown") next = Math.min(list.length - 1, cur + 1);
    else if (e.key === "ArrowLeft" || e.key === "ArrowUp") next = cur <= 0 ? 0 : cur - 1;
    else if (e.key === "Escape") next = null;
    if (next === undefined) return;
    e.preventDefault();
    setActiveKey(next === null ? null : keyOf(list[next]));
  };

  const summary = `${pairLabel} day by day around ${withPath.length} central bank meetings in the last 12 months, from ${days} trading days before the decision to ${days} after, against the last fix before the decision. ${study.banks
    .map((b) => bankTakeaway(b, pairLabel, study.meetings))
    .join(" ")}`;

  return (
    <section className="card study" aria-labelledby="study-title" data-testid="meeting-study">
      <h2 id="study-title" className="card-title">
        How {pairLabel} moved around meetings, last 12 months
      </h2>

      <ul className="study-banks" data-testid="study-banks">
        {banks.map((bank) => {
          const b = study.banks.find((s) => s.bank === bank)!;
          return (
            <li key={bank} data-bank={bank} className={focusBank && focusBank !== bank ? "is-muted" : undefined}>
              <span data-testid={`study-takeaway-${bank}`}>{bankTakeaway(b, pairLabel, study.meetings)}</span>
            </li>
          );
        })}
      </ul>

      {!focusBank && banks.length > 1 && (
        <div className="segmented study-pick" role="group" aria-label="Highlight a bank">
          {banks.map((b) => (
            <button
              key={b}
              type="button"
              className={b === highlight ? "seg seg-active" : "seg"}
              aria-pressed={b === highlight}
              onClick={() => {
                setPicked(b);
                setActiveKey(null);
              }}
            >
              {bankName(b)}
            </button>
          ))}
        </div>
      )}

      <div className="study-readout" id={readoutId} aria-live="polite" data-testid="study-readout">
        {active ? (
          <>
            <strong>
              {bankName(active.bank)}, {fmtDate(active.date)}
            </strong>
            <span>
              surprise {active.surprise_bps === null ? "n/a" : `${fmtNum(active.surprise_bps, 1)} bps`}, tone{" "}
              {toneWord(active.hawkish_score)}
            </span>
            <span className="num">
              {READ_AT.map((k) => `${k > 0 ? `+${k}` : `\u2212${-k}`}: ${pctS(pctAt(active, k))}`).join(", ")}
            </span>
          </>
        ) : (
          <span className="readout-hint">Hover or tap a line, or pick a meeting below, to read its path.</span>
        )}
      </div>

      <div
        ref={ref}
        className="study-frame"
        tabIndex={0}
        aria-describedby={readoutId}
        aria-label={`${pairLabel} paths around ${bankName(highlight)} meetings. Use the arrow keys to step through them.`}
        onKeyDown={onKey}
      >
        {width > 0 && (
          <svg className="study-svg" width={width} height={height} role="img" aria-label={summary} data-testid="study-chart">
            <g transform={`translate(${M.left},${M.top})`}>
              {/* typical distance from the pre-decision level, for the highlighted bank */}
              {envelope.length > 1 && (
                <path
                  className="study-envelope"
                  data-testid="study-envelope"
                  d={`${envelope.map((p, i) => `${i ? "L" : "M"}${x(p.offset).toFixed(1)},${y(p.mean_abs_pct).toFixed(1)}`).join("")}${[...envelope]
                    .reverse()
                    .map((p) => `L${x(p.offset).toFixed(1)},${y(-p.mean_abs_pct).toFixed(1)}`)
                    .join("")}Z`}
                />
              )}
              {yTicks.map((t) => (
                <g key={t}>
                  <line className={t === 0 ? "study-zero" : "study-grid"} x1={0} x2={innerW} y1={y(t)} y2={y(t)} />
                  <text className="study-tick" x={innerW + 8} y={y(t)} dy="0.32em">
                    {pctS(t, 1)}
                  </text>
                </g>
              ))}
              <line className="study-decision" x1={decisionX} x2={decisionX} y1={-8} y2={innerH} />
              <text className="study-decision-label" x={decisionX} y={-12} textAnchor="middle">
                {bankName(highlight)} decision
              </text>

              {ordered.map((m) => {
                const isHl = m.bank === highlight;
                const isActive = active !== null && keyOf(active) === keyOf(m);
                return (
                  <LinePath<PathPoint>
                    key={keyOf(m)}
                    className={`study-line${isHl ? " is-hl" : ""}${isActive ? " is-active" : ""}`}
                    data-testid="study-line"
                    data-bank={m.bank}
                    data-date={m.date}
                    data={m.path ?? []}
                    x={(p) => x(p.offset)}
                    y={(p) => y(p.pct)}
                    curve={curveMonotoneX}
                  />
                );
              })}
              {active && (
                <g className="study-active-points">
                  <LinePath<PathPoint>
                    className="study-line is-active"
                    data={active.path ?? []}
                    x={(p) => x(p.offset)}
                    y={(p) => y(p.pct)}
                    curve={curveMonotoneX}
                  />
                  {READ_AT.map((k) => {
                    const v = pctAt(active, k);
                    return v === null ? null : <circle key={k} cx={x(k)} cy={y(v)} r={k === 1 ? 4.5 : 3} />;
                  })}
                </g>
              )}

              <text className="study-tick" x={0} y={innerH + 18} textAnchor="start">
                {days} days before
              </text>
              <text className="study-tick" x={decisionX} y={innerH + 18} textAnchor="middle">
                decision
              </text>
              <text className="study-tick" x={innerW} y={innerH + 18} textAnchor="end">
                {days} days after
              </text>
              <rect
                className="fan-overlay"
                x={0}
                y={0}
                width={innerW}
                height={innerH}
                onPointerMove={onPointer}
                onPointerDown={onPointer}
                onPointerLeave={(e) => {
                  if (e.pointerType === "mouse") setActiveKey(null);
                }}
              />
            </g>
          </svg>
        )}
      </div>
      <p className="study-legend">
        <span className="study-legend-line" /> {bankName(highlight)} meetings{" "}
        <span className="study-legend-other" /> other banks <span className="study-legend-band" /> typical distance from
        the pre-decision level. % against the last fix before the decision.
      </p>

      {hlMeetings.length > 0 && (
        <div className="study-chips" role="group" aria-label={`${bankName(highlight)} meetings`}>
          {hlMeetings.map((m) => (
            <button
              key={keyOf(m)}
              type="button"
              className={active && keyOf(active) === keyOf(m) ? "study-chip is-active" : "study-chip"}
              aria-pressed={active !== null && keyOf(active) === keyOf(m)}
              onClick={() => setActiveKey(active && keyOf(active) === keyOf(m) ? null : keyOf(m))}
            >
              {fmtShortDate(m.date)}
            </button>
          ))}
        </div>
      )}

      <details className="study-table-wrap" open={study.meetings.length <= 8}>
        <summary>All meetings ({study.meetings.length})</summary>
        <div className="table-scroll">
          <table className="table study-table" data-testid="study-table">
            <thead>
              <tr>
                <th scope="col">Date</th>
                <th scope="col">Bank</th>
                <th scope="col" className="num-col">
                  Surprise
                </th>
                <th scope="col">Tone</th>
                <th scope="col" className="num-col">
                  5 days before
                </th>
                <th scope="col" className="num-col">
                  Decision
                </th>
                <th scope="col" className="num-col">
                  10 days after
                </th>
                <th scope="col">Followed</th>
              </tr>
            </thead>
            <tbody>
              {study.meetings.map((m) => (
                <tr key={keyOf(m)} data-bank={m.bank}>
                  <td>{fmtDate(m.date)}</td>
                  <td>{bankName(m.bank)}</td>
                  <td className="num num-col">{m.surprise_bps === null ? "n/a" : `${fmtNum(m.surprise_bps, 1)} bps`}</td>
                  <td>{toneWord(m.hawkish_score)}</td>
                  <td className="num num-col">{pctS(pctAt(m, -5) ?? (m.run_up_pct === null ? null : -m.run_up_pct))}</td>
                  <td className="num num-col">{pctS(m.reaction_pct)}</td>
                  <td className="num num-col">{pctS(pctAt(m, 10))}</td>
                  <td>{followedWord(m)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </details>
      <p className="disclaimer" data-testid="disclaimer">
        {DISCLAIMER}
      </p>
    </section>
  );
}
