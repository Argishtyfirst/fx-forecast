import { useState } from "react";
import { api } from "../api/client";
import type { DecisionOut, PairId, UpcomingMeeting } from "../api/types";
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
  atlanta_fed: "Atlanta Fed market path",
  previous_rate: "previous rate, no change",
};

export function EventsView({ pair, bank, onBank }: EventsViewProps) {
  const filter = BANKS.find((b) => b === bank?.toUpperCase());
  // Two years of decisions is plenty for the list; the API filters by date.
  const from = addDays(isoDate(new Date()), -730);
  const events = useApi(`events:${from}`, () => api.events(undefined, from));
  const decisions = (events.data?.decisions ?? []).filter((d) => !filter || d.bank === filter);
  const upcoming = (events.data?.upcoming ?? []).filter((m) => !filter || m.bank === filter);
  const pairBanks = PAIRS[pair].banks;
  const study = useApi(`meetings:${pair}`, () => api.meetings(pair, 365));

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
                  <DecisionItem key={d.id} d={d} />
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

function DecisionItem({ d }: { d: DecisionOut }) {
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
          {d.scorer_version && <p className="scorer">scorer {d.scorer_version}</p>}
        </div>
      </div>

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
