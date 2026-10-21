import { useState } from "react";
import { api } from "../api/client";
import type { DecisionOut, MeetingReactionOut, PairId, UpcomingMeeting } from "../api/types";
import { DataStatus } from "../components/DataStatus";
import { HawkishScale } from "../components/HawkishScale";
import { MeetingStudy } from "../components/MeetingStudy";
import { ExternalIcon, MinusIcon, PlusIcon } from "../components/Icons";
import { EmptyState, ErrorState, Loading } from "../components/States";
import { BANK_LABELS, BANK_LONG, BANKS, EVENT_SOURCES, PAIRS, RATE_TYPE_LABELS } from "../lib/constants";
import {
  addDays,
  fmtBps,
  fmtDaysUntil,
  fmtPercentValue,
  fmtWeekdayDate,
  isoDate,
  titleCase,
} from "../lib/format";
import { useApi } from "../lib/useApi";

interface EventsViewProps {
  pair: PairId;
  bank?: string;
  onBank: (bank: string | undefined) => void;
}

const EXPECTED_SOURCE_LABELS: Record<string, string> = {
  atlanta_fed: "Atlanta Fed market expectation",
  atlanta_fed_mpt: "Atlanta Fed market expectation",
  previous_rate: "previous rate, no change",
};

/** Who scored the statement's tone, in plain words. */
function scorerLabel(version: string): string {
  const model = version.split("@")[0];
  if (model.startsWith("lexicon")) return "Scored by word count (fallback until Gemini scores it)";
  if (model.startsWith("gemini")) return `Scored by Gemini (${model})`;
  if (model.startsWith("claude")) return `Scored by Claude (${model})`;
  return `Scored by ${model}`;
}

const signedPct = (v: number | null | undefined) =>
  v == null ? "n/a" : `${v > 0 ? "+" : v < 0 ? "\u2212" : ""}${Math.abs(v).toFixed(2)}%`;

export function EventsView({ pair, bank, onBank }: EventsViewProps) {
  const filter = BANKS.find((b) => b === bank?.toUpperCase());
  // Two years of decisions is plenty for the list; the API filters by date.
  const from = addDays(isoDate(new Date()), -730);
  const events = useApi(`events:${from}`, () => api.events(undefined, from));
  const decisions = (events.data?.decisions ?? []).filter((d) => !filter || d.bank === filter);
  const upcoming = (events.data?.upcoming ?? []).filter((m) => !filter || m.bank === filter);
  const pairBanks = PAIRS[pair].banks;
  const study = useApi(`meetings:${pair}`, () => api.meetings(pair, 365));
  // The same study over the decision list's two years, to show each decision's move.
  const moves = useApi(`meetings:${pair}:730`, () => api.meetings(pair, 730));
  const moveByDecision = new Map(
    (moves.data?.meetings ?? []).map((m) => [`${m.bank}|${m.date}`, m] as const),
  );

  return (
    <div className="view">
      <DataStatus relevant={EVENT_SOURCES} />
      <section className="view-head">
        <div>
          <h1 className="view-title">Central bank events</h1>
          <p className="view-sub">
            Decisions, surprises and statement changes. {PAIRS[pair].label} follows{" "}
            {joinWords(pairBanks.map((b) => BANK_LABELS[b]))}.
          </p>
        </div>
        <div className="segmented" role="group" aria-label="Bank filter">
          <button
            type="button"
            className={!filter ? "seg seg-active" : "seg"}
            aria-pressed={!filter}
            onClick={() => onBank(undefined)}
          >
            All
          </button>
          {BANKS.map((b) => (
            <button
              key={b}
              type="button"
              className={filter === b ? "seg seg-active" : "seg"}
              aria-pressed={filter === b}
              onClick={() => onBank(b)}
            >
              {BANK_LABELS[b]}
            </button>
          ))}
        </div>
      </section>

      {study.error ? (
        <ErrorState title="Could not load the meeting study" error={study.error} onRetry={study.reload} />
      ) : study.loading ? (
        <Loading label="Loading the meeting study" height={240} />
      ) : study.data && study.data.meetings.length > 0 ? (
        <MeetingStudy study={study.data} pairLabel={PAIRS[pair].label} focusBank={filter} />
      ) : (
        <EmptyState title="No meeting study yet">It appears once a meeting has a fix before and after it.</EmptyState>
      )}

      {events.error ? (
        <ErrorState title="Could not load the events" error={events.error} onRetry={events.reload} />
      ) : events.loading ? (
        <Loading label="Loading central bank events" height={320} />
      ) : (
        <div className="events-layout">
          <section className="card" aria-labelledby="upcoming-title">
            <h2 id="upcoming-title" className="card-title">
              Upcoming meetings
            </h2>
            {upcoming.length ? (
              <ul className="upcoming" data-testid="upcoming-list">
                {upcoming.map((m) => (
                  <UpcomingRow key={`${m.bank}-${m.date}`} m={m} />
                ))}
              </ul>
            ) : (
              <EmptyState title="No scheduled meetings stored" />
            )}
          </section>

          <section className="card" aria-labelledby="decisions-title">
            <h2 id="decisions-title" className="card-title">
              Past decisions
            </h2>
            {decisions.length ? (
              <ol className="decisions" data-testid="decision-list">
                {decisions.map((d) => (
                  <DecisionItem
                    key={d.id}
                    d={d}
                    pairLabel={PAIRS[pair].label}
                    move={moveByDecision.get(`${d.bank}|${d.date}`)}
                  />
                ))}
              </ol>
            ) : (
              <EmptyState title="No decisions recorded yet" />
            )}
          </section>
        </div>
      )}
    </div>
  );
}

function joinWords(items: string[]): string {
  return items.length < 2 ? items.join("") : `${items.slice(0, -1).join(", ")} and ${items[items.length - 1]}`;
}

function UpcomingRow({ m }: { m: UpcomingMeeting }) {
  return (
    <li className="upcoming-row" data-bank={m.bank}>
      <span className="bank-tag">{BANK_LABELS[m.bank] ?? m.bank}</span>
      <time dateTime={m.date} className="upcoming-date">
        {fmtWeekdayDate(m.date)}
      </time>
      <span className="upcoming-until num">{fmtDaysUntil(m.days_until)}</span>
      {!m.scheduled && <span className="tag tag-warn">Unscheduled</span>}
    </li>
  );
}

function decisionVerb(d: DecisionOut): string {
  if (d.rate_before == null || d.rate_after == null) return "Decision";
  const bps = Math.round((d.rate_after - d.rate_before) * 100);
  if (bps === 0) return "Hold";
  return bps > 0 ? `Hike ${bps} bps` : `Cut ${-bps} bps`;
}

function followedText(m: MeetingReactionOut): string | null {
  if (m.followed === true) return "moved the way the surprise or tone implied";
  if (m.followed === false) return "moved against the surprise or tone";
  if (m.expected_sign === 0) return null;
  return null;
}

/** One sentence from the path: which way the decision moved the pair, and what came after. */
export function pathSentence(m: MeetingReactionOut): string | null {
  const at = (k: number) => m.path?.find((p) => p.offset === k)?.pct ?? null;
  const r = at(1) ?? m.reaction_pct;
  const lastPoint = m.path && m.path.length ? m.path[m.path.length - 1] : null;
  if (!lastPoint || lastPoint.offset < 2) return null;
  const e = lastPoint.pct;
  const later = `${lastPoint.offset} days later`;
  const abs = (v: number) => `${Math.abs(v).toFixed(2)}%`;
  if (Math.abs(r) < 0.05) return `Barely moved on the decision; ${signedPct(e)} ${later}.`;
  const verb = r < 0 ? "Fell" : "Rose";
  const going = r < 0 ? "kept falling" : "kept rising";
  if (Math.sign(e) !== Math.sign(r) && Math.abs(e) >= 0.05) return `${verb} ${abs(r)} on the decision, then reversed: ${signedPct(e)} ${later}.`;
  if (Math.abs(e) > Math.abs(r) + 0.05) return `${verb} ${abs(r)} on the decision and ${going}: ${signedPct(e)} ${later}.`;
  if (Math.abs(e) < Math.abs(r) - 0.05) return `${verb} ${abs(r)} on the decision, then gave some back: ${signedPct(e)} ${later}.`;
  return `${verb} ${abs(r)} on the decision and held there: ${signedPct(e)} ${later}.`;
}

/** A compact sparkline of the pair's path around this decision, 10 trading days each side. */
function DecisionMove({ m, pairLabel }: { m: MeetingReactionOut; pairLabel: string }) {
  const followed = followedText(m);
  const path = m.path ?? [];
  const sentence = pathSentence(m);
  if (path.length < 2) return null;
  const W = 240;
  const H = 56;
  const pad = { l: 2, r: 4, t: 6, b: 6 };
  const offs = path.map((p) => p.offset);
  const lo = Math.min(...offs);
  const hi = Math.max(10, ...offs);
  const ext = Math.max(0.2, ...path.map((p) => Math.abs(p.pct))) * 1.15;
  const x = (k: number) => pad.l + ((k - lo) / (hi - lo)) * (W - pad.l - pad.r);
  const y = (v: number) => pad.t + ((ext - v) / (2 * ext)) * (H - pad.t - pad.b);
  const d = path.map((p, i) => `${i ? "L" : "M"}${x(p.offset).toFixed(1)},${y(p.pct).toFixed(1)}`).join("");
  const reaction = path.find((p) => p.offset === 1);
  const at5 = path.find((p) => p.offset === 5);
  const at10 = path.find((p) => p.offset === 10);
  const label = `${pairLabel} around this decision: ${sentence ?? ""}`;
  return (
    <div className="decision-move" data-testid="decision-move">
      <p className="decision-move-title">{pairLabel} around this decision</p>
      <div className="decision-spark">
        <svg viewBox={`0 0 ${W} ${H}`} width={W} height={H} role="img" aria-label={label} className="spark">
          <line className="spark-zero" x1={pad.l} x2={W - pad.r} y1={y(0)} y2={y(0)} />
          <line className="spark-decision" x1={x(0.5)} x2={x(0.5)} y1={2} y2={H - 2} />
          <path className="spark-line" d={d} />
          {reaction && <circle className="spark-reaction" cx={x(1)} cy={y(reaction.pct)} r={3.5} />}
        </svg>
        <dl className="spark-ends">
          {at5 && (
            <div>
              <dt>+5 days</dt>
              <dd className="num">{signedPct(at5.pct)}</dd>
            </div>
          )}
          {at10 && (
            <div>
              <dt>+10 days</dt>
              <dd className="num">{signedPct(at10.pct)}</dd>
            </div>
          )}
        </dl>
      </div>
      {sentence && <p className="decision-move-sentence">{sentence}</p>}
      {followed && <p className="decision-move-note">The reaction {followed}.</p>}
    </div>
  );
}

function DecisionItem({ d, pairLabel, move }: { d: DecisionOut; pairLabel: string; move?: MeetingReactionOut }) {
  const [open, setOpen] = useState(false);
  const diff = d.statement_diff;
  const added = diff?.added ?? [];
  const removed = diff?.removed ?? [];
  const otherRates = Object.entries(d.rates ?? {}).filter(([k]) => k !== d.rate_type);
  const diffId = `diff-${d.id}`;

  return (
    <li className="decision" data-bank={d.bank} data-testid="decision">
      <div className="decision-head">
        <span className="bank-tag" title={BANK_LONG[d.bank]}>
          {BANK_LABELS[d.bank] ?? d.bank}
        </span>
        <time dateTime={d.date} className="decision-date">
          {fmtWeekdayDate(d.date)}
        </time>
        <span className="decision-verb">{decisionVerb(d)}</span>
      </div>

      <dl className="decision-facts">
        <div>
          <dt>{RATE_TYPE_LABELS[d.rate_type] ?? titleCase(d.rate_type)}</dt>
          <dd className="num">
            {fmtPercentValue(d.rate_before, 3)} <span className="arrow">&rarr;</span> {fmtPercentValue(d.rate_after, 3)}
          </dd>
        </div>
        <div>
          <dt>Expected</dt>
          <dd className="num">
            {fmtPercentValue(d.expected, 3)}
            {d.expected_source && (
              <span className="cell-sub">{EXPECTED_SOURCE_LABELS[d.expected_source] ?? d.expected_source}</span>
            )}
          </dd>
        </div>
        <div>
          <dt>Surprise</dt>
          <dd className="num decision-surprise">{fmtBps(d.surprise_bps)}</dd>
        </div>
      </dl>

      {otherRates.length > 0 && (
        <p className="decision-rates">
          {otherRates.map(([k, v]) => (
            <span key={k}>
              {RATE_TYPE_LABELS[k] ?? titleCase(k)}{" "}
              <span className="num">
                {fmtPercentValue(v.before, 2)} &rarr; {fmtPercentValue(v.after, 2)}
              </span>
            </span>
          ))}
        </p>
      )}

      <div className="decision-score">
        <HawkishScale score={d.hawkish_score} compact />
        <div className="decision-reason">
          <p>{d.hawkish_reason ?? "This statement has not been scored yet."}</p>
          {d.scorer_version && <p className="scorer">{scorerLabel(d.scorer_version)}</p>}
        </div>
      </div>

      {move && <DecisionMove m={move} pairLabel={pairLabel} />}

      <div className="decision-actions">
        {diff ? (
          <button
            type="button"
            className="disclosure"
            aria-expanded={open}
            aria-controls={diffId}
            onClick={() => setOpen((o) => !o)}
          >
            {open ? <MinusIcon size={14} /> : <PlusIcon size={14} />}
            Statement changes
            <span className="disclosure-count num">
              +{added.length} &minus;{removed.length}
            </span>
          </button>
        ) : (
          <span className="muted small">No previous statement to compare</span>
        )}
        {d.statement_url && (
          <a className="ext-link" href={d.statement_url} target="_blank" rel="noreferrer">
            Full statement <ExternalIcon size={13} />
          </a>
        )}
      </div>

      {diff && open && (
        <div id={diffId} className="diff" data-testid="statement-diff">
          {removed.length === 0 && added.length === 0 && <p className="muted small">No sentence changed.</p>}
          {removed.map((s, i) => (
            <p key={`r${i}`} className="diff-line diff-removed">
              <span className="diff-mark" aria-label="Removed">
                &minus;
              </span>
              <span>{s}</span>
            </p>
          ))}
          {added.map((s, i) => (
            <p key={`a${i}`} className="diff-line diff-added">
              <span className="diff-mark" aria-label="Added">
                +
              </span>
              <span>{s}</span>
            </p>
          ))}
        </div>
      )}
    </li>
  );
}
