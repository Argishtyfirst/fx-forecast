import { curveMonotoneX } from "@visx/curve";
import { scaleLinear } from "@visx/scale";
import { LinePath } from "@visx/shape";
import { useId, useState } from "react";
import type { BankReactionSummaryOut, MeetingReactionOut, MeetingStudyResponse, PathPoint } from "../api/types";
import { t } from "../i18n";
import { BANK_LABELS, BANKS } from "../lib/constants";
import { fmtBps, fmtDate, fmtNum, fmtShortDate, fmtSignedPct } from "../lib/format";
import { useWidth } from "../lib/useWidth";

interface MeetingStudyProps {
  study: MeetingStudyResponse;
  pairLabel: string;
  /** Bank picked in the Events filter; it gets the accent, the others stay grey. */
  focusBank?: string;
}

export const pctS = (x: number | null | undefined, digits = 2) => fmtSignedPct(x, digits);

export function ratioWord(r: number): string {
  return t("study.about", { ratio: r >= 2 ? fmtNum(Math.round(r), 0) : fmtNum(r, 1) });
}

/** The plain-language takeaway for one bank. */
export function bankTakeaway(b: BankReactionSummaryOut, pairLabel: string, meetings: MeetingReactionOut[]): string {
  const name = BANK_LABELS[b.bank] ?? b.bank;
  const parts: string[] = [];
  if (b.mean_abs_reaction_pct !== null && b.reaction_ratio !== null) {
    parts.push(
      t("study.moved", {
        bank: name,
        pair: pairLabel,
        pct: fmtNum(b.mean_abs_reaction_pct, 2),
        ratio: ratioWord(b.reaction_ratio),
      }),
    );
  } else {
    parts.push(t("study.notEnough", { bank: name }));
  }
  const noView = meetings.filter((m) => m.bank === b.bank).every((m) => m.expected_sign === 0);
  if (noView) parts.push(t("study.noDirection"));
  else if (b.n_signed > 0 && b.consistency !== null)
    parts.push(t("study.followed", { k: Math.round(b.consistency * b.n_signed), count: b.n_signed, n: b.n_signed }));
  else parts.push(t("study.noSignal"));
  let text = parts.join(", ");
  if (b.n < 10) text += ` ${t("study.small", { count: b.n, n: b.n })}`;
  return `${text}${t("fmt.stop")}`;
}

export function toneWord(score: number | null): string {
  if (score === null) return t("tone.notScored").toLowerCase();
  if (score <= -0.15) return t("tone.dovish").toLowerCase();
  if (score >= 0.15) return t("tone.hawkish").toLowerCase();
  return t("tone.neutral").toLowerCase();
}

function followedWord(m: MeetingReactionOut): string {
  if (m.followed === null) return m.expected_sign === 0 ? t("study.noDirection") : t("study.noSignalShort");
  return m.followed ? t("study.yes") : t("study.no");
}

const M = { top: 22, right: 48, bottom: 30, left: 6 };
const READ_AT = [-5, 1, 5, 10];

const pctAt = (m: MeetingReactionOut, k: number) => m.path?.find((p) => p.offset === k)?.pct ?? null;

type DecisionFilter = "all" | "hike" | "hold" | "cut";
type SurpriseFilter = "all" | "hawkish" | "expected" | "dovish";
const DECISION_OPTS: DecisionFilter[] = ["all", "hike", "hold", "cut"];
const SURPRISE_OPTS: SurpriseFilter[] = ["all", "hawkish", "expected", "dovish"];
const decisionWord = (d: DecisionFilter) => (d === "all" ? "" : t(`study.word.${d}`));
const surpriseWord = (s: SurpriseFilter) => (s === "all" ? "" : t(`study.word.${s}`));

function decisionOf(m: MeetingReactionOut): DecisionFilter | null {
  if (m.rate_change_bps === null) return null;
  return m.rate_change_bps > 0 ? "hike" : m.rate_change_bps < 0 ? "cut" : "hold";
}
function surpriseOf(m: MeetingReactionOut): SurpriseFilter {
  const s = m.surprise_bps;
  if (s !== null && s >= 1) return "hawkish";
  if (s !== null && s <= -1) return "dovish";
  return m.signal > 0 ? "hawkish" : m.signal < 0 ? "dovish" : "expected";
}

/** Mean of |pct| (or signed pct) per offset over a set of meetings. */
function perOffset(ms: MeetingReactionOut[], signed: boolean): { offset: number; v: number }[] {
  const by = new Map<number, number[]>();
  for (const m of ms) for (const p of m.path ?? []) by.set(p.offset, [...(by.get(p.offset) ?? []), signed ? p.pct : Math.abs(p.pct)]);
  return [...by.entries()].sort((a, b) => a[0] - b[0]).map(([offset, vs]) => ({ offset, v: vs.reduce((a, b) => a + b, 0) / vs.length }));
}

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
  const [decision, setDecision] = useState<DecisionFilter>("all");
  const [surprise, setSurprise] = useState<SurpriseFilter>("all");
  const filtered = decision !== "all" || surprise !== "all";
  const passes = (m: MeetingReactionOut) =>
    (decision === "all" || decisionOf(m) === decision) && (surprise === "all" || surpriseOf(m) === surprise);
  const readoutId = useId();
  const days = study.path_days ?? 10;

  const matching = study.meetings.filter(passes);
  const withPath = matching.filter((m) => (m.path?.length ?? 0) > 1);
  const visible = withPath.filter((m) => !focusBank || m.bank === focusBank);
  const ordered = [...visible].sort((a, b) => (a.bank === highlight ? 1 : 0) - (b.bank === highlight ? 1 : 0) || a.date.localeCompare(b.date));
  const keyOf = (m: MeetingReactionOut) => `${m.bank}|${m.date}`;
  const active = withPath.find((m) => keyOf(m) === activeKey) ?? null;
  const hlMeetings = withPath.filter((m) => m.bank === highlight).sort((a, b) => b.date.localeCompare(a.date));
  const hlFiltered = withPath.filter((m) => m.bank === highlight);
  const envelope = filtered
    ? perOffset(hlFiltered, false).map((p) => ({ offset: p.offset, mean_abs_pct: p.v, meetings: hlFiltered.length }))
    : (study.banks.find((b) => b.bank === highlight)?.typical_path ?? []);
  const average = filtered && hlFiltered.length > 0 ? perOffset(hlFiltered, true) : [];
  const filterLabel = [decisionWord(decision), surpriseWord(surprise)].filter(Boolean).join(", ");
  const filteredSentence = (bank: string) => {
    const ms = matching.filter((m) => m.bank === bank);
    const name = BANK_LABELS[bank] ?? bank;
    if (!ms.length) return t("study.fNone", { bank: name, filter: filterLabel });
    const mean = ms.reduce((a, m) => a + Math.abs(m.reaction_pct), 0) / ms.length;
    return t(ms.length <= 2 ? "study.fSomeSmall" : "study.fSome", {
      bank: name,
      filter: filterLabel,
      count: ms.length,
      n: ms.length,
      pair: pairLabel,
      pct: fmtNum(mean, 2),
    });
  };

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

  const summary = `${t("study.aria", { pair: pairLabel, count: withPath.length, n: withPath.length, days })} ${study.banks
    .map((b) => bankTakeaway(b, pairLabel, study.meetings))
    .join(" ")}`;

  return (
    <section className="card study" aria-labelledby="study-title" data-testid="meeting-study">
      <h2 id="study-title" className="card-title">
        {t("study.title", { pair: pairLabel })}
      </h2>

      <ul className="study-banks" data-testid="study-banks">
        {banks.map((bank) => {
          const b = study.banks.find((s) => s.bank === bank)!;
          return (
            <li key={bank} data-bank={bank} className={focusBank && focusBank !== bank ? "is-muted" : undefined}>
              <span data-testid={`study-takeaway-${bank}`}>
                {filtered ? filteredSentence(bank) : bankTakeaway(b, pairLabel, study.meetings)}
              </span>
            </li>
          );
        })}
      </ul>

      <div className="study-filters">
        <div className="study-filter">
          <span className="study-filter-label" id="f-decision">
            {t("study.decision")}
          </span>
          <div className="segmented" role="group" aria-labelledby="f-decision">
            {DECISION_OPTS.map((v) => (
              <button key={v} type="button" className={decision === v ? "seg seg-active" : "seg"} aria-pressed={decision === v} onClick={() => { setDecision(v); setActiveKey(null); }}>
                {t(`study.opt.${v}`)}
              </button>
            ))}
          </div>
        </div>
        <div className="study-filter">
          <span className="study-filter-label" id="f-surprise">
            {t("study.surprise")}
          </span>
          <div className="segmented" role="group" aria-labelledby="f-surprise">
            {SURPRISE_OPTS.map((v) => (
              <button key={v} type="button" className={surprise === v ? "seg seg-active" : "seg"} aria-pressed={surprise === v} onClick={() => { setSurprise(v); setActiveKey(null); }}>
                {t(`study.opt.${v}`)}
              </button>
            ))}
          </div>
        </div>
        <p className="study-filter-hint">{t("study.hint")}</p>
      </div>

      {!focusBank && banks.length > 1 && (
        <div className="segmented study-pick" role="group" aria-label={t("study.highlightAria")}>
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
              {t("study.readSurprise", { surprise: fmtBps(active.surprise_bps), tone: toneWord(active.hawkish_score) })}
            </span>
            <span className="num">
              {READ_AT.map((k) => `${k > 0 ? `+${k}` : `\u2212${-k}`}: ${pctS(pctAt(active, k))}`).join(", ")}
            </span>
          </>
        ) : (
          <span className="readout-hint">{t("study.readHint")}</span>
        )}
      </div>

      <div
        ref={ref}
        className="study-frame"
        tabIndex={0}
        aria-describedby={readoutId}
        aria-label={t("study.frameAria", { pair: pairLabel, bank: bankName(highlight) })}
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
                {t("study.bankDecision", { bank: bankName(highlight) })}
              </text>

              {average.length > 1 && (
                <g data-testid="study-average">
                  <path
                    className="study-average"
                    d={average.map((p, i) => `${i ? "L" : "M"}${x(p.offset).toFixed(1)},${y(p.v).toFixed(1)}`).join("")}
                  />
                  <text className="study-average-label" x={x(average[average.length - 1].offset) - 4} y={y(average[average.length - 1].v) - 6} textAnchor="end">
                    {t("study.average")}
                  </text>
                </g>
              )}
              {visible.length === 0 && (
                <text className="study-empty" x={innerW / 2} y={innerH / 2} textAnchor="middle">
                  {t("study.noMatch")}
                </text>
              )}
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
                {t("study.daysBefore", { count: days, n: days })}
              </text>
              <text className="study-tick" x={decisionX} y={innerH + 18} textAnchor="middle">
                {t("study.decisionTick")}
              </text>
              <text className="study-tick" x={innerW} y={innerH + 18} textAnchor="end">
                {t("study.daysAfter", { count: days, n: days })}
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
        <span className="study-legend-line" /> {t("study.legendBank", { bank: bankName(highlight) })}{" "}
        <span className="study-legend-other" /> {t("study.legendOther")} <span className="study-legend-band" />{" "}
        {t("study.legendBand")}
      </p>

      {hlMeetings.length > 0 && (
        <div className="study-chips" role="group" aria-label={t("study.legendBank", { bank: bankName(highlight) })}>
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

      <details className="study-table-wrap" open={matching.length <= 8}>
        <summary>{t(filtered ? "study.tableMatching" : "study.tableAll", { n: matching.length })}</summary>
        <div className="table-scroll">
          <table className="table study-table" data-testid="study-table">
            <thead>
              <tr>
                <th scope="col">{t("study.col.date")}</th>
                <th scope="col">{t("study.col.bank")}</th>
                <th scope="col" className="num-col">
                  {t("study.col.surprise")}
                </th>
                <th scope="col">{t("study.col.tone")}</th>
                <th scope="col" className="num-col">
                  {t("study.daysBefore", { count: 5, n: 5 })}
                </th>
                <th scope="col" className="num-col">
                  {t("study.col.decision")}
                </th>
                <th scope="col" className="num-col">
                  {t("study.daysAfter", { count: 10, n: 10 })}
                </th>
                <th scope="col">{t("study.col.followed")}</th>
              </tr>
            </thead>
            <tbody>
              {matching.map((m) => (
                <tr key={keyOf(m)} data-bank={m.bank}>
                  <td>{fmtDate(m.date)}</td>
                  <td>{bankName(m.bank)}</td>
                  <td className="num num-col">{fmtBps(m.surprise_bps)}</td>
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
        {t("disclaimer")}
      </p>
    </section>
  );
}
