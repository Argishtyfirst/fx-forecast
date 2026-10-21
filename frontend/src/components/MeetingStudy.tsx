import { scaleLinear, scaleTime } from "@visx/scale";
import { useId, useMemo, useState } from "react";
import type { BankReactionSummaryOut, MeetingReactionOut, MeetingStudyResponse } from "../api/types";
import { BANK_LABELS, BANKS, DISCLAIMER } from "../lib/constants";
import { addDays, fmtDate, fmtNum, parseDate } from "../lib/format";
import { useWidth } from "../lib/useWidth";

interface MeetingStudyProps {
  study: MeetingStudyResponse;
  pairLabel: string;
  /** Bank picked in the Events filter; it gets the accent, the others stay grey. */
  focusBank?: string;
}

const pctS = (x: number | null | undefined, digits = 2) => {
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

function toneWord(score: number | null): string {
  if (score === null) return "not scored";
  if (score <= -0.15) return "dovish";
  if (score >= 0.15) return "hawkish";
  return "neutral";
}

function followedWord(m: MeetingReactionOut): string {
  if (m.followed === null) return m.expected_sign === 0 ? "no expected direction" : "no signal";
  return m.followed ? "yes" : "no";
}

const SHAPE: Record<string, "circle" | "square" | "diamond"> = { FED: "circle", ECB: "square", CBA: "diamond" };

function Mark({ shape, x, y, r }: { shape: "circle" | "square" | "diamond"; x: number; y: number; r: number }) {
  if (shape === "square") return <rect x={x - r} y={y - r} width={2 * r} height={2 * r} rx={1} />;
  if (shape === "diamond") return <path d={`M${x},${y - r - 1}L${x + r + 1},${y}L${x},${y + r + 1}L${x - r - 1},${y}Z`} />;
  return <circle cx={x} cy={y} r={r} />;
}

const M = { top: 10, right: 52, bottom: 24, left: 4 };

/**
 * Meeting reaction study: per bank, how big the move around its meetings was against a normal
 * day and whether it followed the surprise or tone; then one mark per meeting (the reaction, with
 * ticks for the run-up before and the follow-through after) and the list of meetings.
 */
export function MeetingStudy({ study, pairLabel, focusBank }: MeetingStudyProps) {
  const [ref, width] = useWidth<HTMLDivElement>(720);
  const [active, setActive] = useState<number | null>(null);
  const readoutId = useId();
  const banks = BANKS.filter((b) => study.banks.some((s) => s.bank === b));
  const meetings = study.meetings; // most recent first
  const chrono = useMemo(() => [...meetings].sort((a, b) => a.date.localeCompare(b.date)), [meetings]);

  const height = 220;
  const innerW = Math.max(width - M.left - M.right, 10);
  const innerH = height - M.top - M.bottom;
  const start = addDays(study.as_of, -study.lookback_days);
  const x = scaleTime({ domain: [parseDate(start), parseDate(study.as_of)], range: [8, innerW - 8] });
  const values = meetings.flatMap((m) => [m.reaction_pct, m.run_up_pct ?? 0, m.follow_pct ?? 0]);
  const normal = Math.max(0, ...study.banks.map((b) => b.normal_abs_move_pct ?? 0));
  const ext = Math.max(normal, ...values.map(Math.abs)) * 1.15 || 1;
  const y = scaleLinear<number>({ domain: [-ext, ext], range: [innerH, 0], nice: true });
  const ticks = y.ticks(4);
  const months = x.ticks(width < 480 ? 4 : 6);
  const activeM = active !== null ? chrono[active] : null;

  const onPointer = (e: React.PointerEvent<SVGRectElement>) => {
    const px = e.clientX - e.currentTarget.getBoundingClientRect().left;
    let best = 0;
    chrono.forEach((m, i) => {
      if (Math.abs(x(parseDate(m.date)) - px) < Math.abs(x(parseDate(chrono[best].date)) - px)) best = i;
    });
    setActive(best);
  };
  const onKey = (e: React.KeyboardEvent<HTMLDivElement>) => {
    if (!chrono.length) return;
    const last = chrono.length - 1;
    const cur = active ?? last;
    const next =
      e.key === "ArrowLeft" ? Math.max(0, cur - 1) : e.key === "ArrowRight" ? Math.min(last, cur + 1) : e.key === "Home" ? 0 : e.key === "End" ? last : e.key === "Escape" ? null : undefined;
    if (next === undefined) return;
    e.preventDefault();
    setActive(next);
  };

  const summary = `${pairLabel} moves around ${meetings.length} central bank meetings in the last ${Math.round(
    study.lookback_days / 30.4,
  )} months. ${study.banks.map((b) => bankTakeaway(b, pairLabel, meetings)).join(" ")} Normal day move about ${fmtNum(normal, 2)}%.`;

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
              <svg className={`study-key ${focusBank === bank ? "is-focus" : ""}`} width={14} height={14} aria-hidden="true">
                <Mark shape={SHAPE[bank] ?? "circle"} x={7} y={7} r={4} />
              </svg>
              <span data-testid={`study-takeaway-${bank}`}>{bankTakeaway(b, pairLabel, meetings)}</span>
            </li>
          );
        })}
      </ul>

      <div className="study-readout" id={readoutId} aria-live="polite">
        {activeM ? (
          <>
            <strong>
              {BANK_LABELS[activeM.bank] ?? activeM.bank}, {fmtDate(activeM.date)}
            </strong>
            <span>
              surprise {activeM.surprise_bps === null ? "n/a" : `${fmtNum(activeM.surprise_bps, 1)} bps`}, tone{" "}
              {toneWord(activeM.hawkish_score)}
            </span>
            <span className="num">
              run-up {pctS(activeM.run_up_pct)}, reaction {pctS(activeM.reaction_pct)}, follow-through{" "}
              {pctS(activeM.follow_pct)}
            </span>
          </>
        ) : (
          <span className="readout-hint">
            Dot: the reaction. Left tick: 5 fixes before. Right tick: 5 fixes after. Grey band: a normal day.
          </span>
        )}
      </div>

      <div
        ref={ref}
        className="study-frame"
        tabIndex={0}
        aria-describedby={readoutId}
        aria-label={`${pairLabel} meeting reactions. Use the arrow keys to read each meeting.`}
        onKeyDown={onKey}
        onBlur={() => setActive(null)}
      >
        {width > 0 && (
          <svg className="study-svg" width={width} height={height} role="img" aria-label={summary} data-testid="study-chart">
            <g transform={`translate(${M.left},${M.top})`}>
              <rect className="study-normal" x={0} width={innerW} y={y(normal)} height={y(-normal) - y(normal)} />
              {ticks.map((t) => (
                <g key={t}>
                  <line className={t === 0 ? "study-zero" : "study-grid"} x1={0} x2={innerW} y1={y(t)} y2={y(t)} />
                  <text className="study-tick" x={innerW + 8} y={y(t)} dy="0.32em">
                    {pctS(t, 1)}
                  </text>
                </g>
              ))}
              {months.map((d) => (
                <text key={d.toISOString()} className="study-tick" x={x(d)} y={innerH + 16} textAnchor="middle">
                  {d.toLocaleString("en-GB", { month: "short", timeZone: "UTC" })}
                </text>
              ))}
              {chrono.map((m, i) => {
                const mx = x(parseDate(m.date));
                const focus = !focusBank || focusBank === m.bank;
                const cls = ["study-mark", focusBank === m.bank ? "is-focus" : "", focus ? "" : "is-muted", active === i ? "is-active" : ""]
                  .filter(Boolean)
                  .join(" ");
                return (
                  <g key={`${m.bank}-${m.date}`} className={cls} data-testid="study-mark" data-bank={m.bank} data-date={m.date}>
                    {m.run_up_pct !== null && <line className="study-tick-line" x1={mx - 7} x2={mx - 2} y1={y(m.run_up_pct)} y2={y(m.run_up_pct)} />}
                    {m.follow_pct !== null && <line className="study-tick-line" x1={mx + 2} x2={mx + 7} y1={y(m.follow_pct)} y2={y(m.follow_pct)} />}
                    <line className="study-stem" x1={mx} x2={mx} y1={y(0)} y2={y(m.reaction_pct)} />
                    <Mark shape={SHAPE[m.bank] ?? "circle"} x={mx} y={y(m.reaction_pct)} r={active === i ? 5 : 4} />
                  </g>
                );
              })}
              {activeM && (
                <line className="study-cursor" x1={x(parseDate(activeM.date))} x2={x(parseDate(activeM.date))} y1={0} y2={innerH} />
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
            </g>
          </svg>
        )}
      </div>

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
                Run-up
              </th>
              <th scope="col" className="num-col">
                Reaction
              </th>
              <th scope="col" className="num-col">
                Follow-through
              </th>
              <th scope="col">Followed</th>
            </tr>
          </thead>
          <tbody>
            {meetings.map((m) => (
              <tr key={`${m.bank}-${m.date}`} data-bank={m.bank}>
                <td>{fmtDate(m.date)}</td>
                <td>{BANK_LABELS[m.bank] ?? m.bank}</td>
                <td className="num num-col">{m.surprise_bps === null ? "n/a" : `${fmtNum(m.surprise_bps, 1)} bps`}</td>
                <td>{toneWord(m.hawkish_score)}</td>
                <td className="num num-col">{pctS(m.run_up_pct)}</td>
                <td className="num num-col">{pctS(m.reaction_pct)}</td>
                <td className="num num-col">{pctS(m.follow_pct)}</td>
                <td>{followedWord(m)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="disclaimer" data-testid="disclaimer">
        {DISCLAIMER}
      </p>
    </section>
  );
}
