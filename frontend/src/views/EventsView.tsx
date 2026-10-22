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
import { t } from "../i18n";
import { fmtNum, fmtSignedPct } from "../lib/format";

interface EventsViewProps {
  pair: PairId;
  bank?: string;
  onBank: (bank: string | undefined) => void;
}

const EXPECTED_SOURCE_LABELS: Record<string, () => string> = {
  atlanta_fed: () => t("events.expAtlanta"),
  atlanta_fed_mpt: () => t("events.expAtlanta"),
  previous_rate: () => t("events.expPrevious"),
};

/** Who scored the statement's tone, in plain words. */
function scorerLabel(version: string): string {
  const model = version.split("@")[0];
  if (model.startsWith("lexicon")) return t("events.scoredLexicon");
  if (model.startsWith("gemini")) return t("events.scoredBy", { name: "Gemini", model });
  if (model.startsWith("claude")) return t("events.scoredBy", { name: "Claude", model });
  return t("events.scoredByModel", { model });
}

const signedPct = (v: number | null | undefined) => fmtSignedPct(v, 2);

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
          <h1 className="view-title">{t("events.title")}</h1>
          <p className="view-sub">
            {t("events.sub", { pair: PAIRS[pair].label, banks: joinWords(pairBanks.map((b) => BANK_LABELS[b])) })}
          </p>
        </div>
        <div className="segmented" role="group" aria-label={t("events.filterAria")}>
          <button
            type="button"
            className={!filter ? "seg seg-active" : "seg"}
            aria-pressed={!filter}
            onClick={() => onBank(undefined)}
          >
            {t("events.all")}
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
        <ErrorState title={t("events.errStudy")} error={study.error} onRetry={study.reload} />
      ) : study.loading ? (
        <Loading label={t("events.loadingStudy")} height={240} />
      ) : study.data && study.data.meetings.length > 0 ? (
        <MeetingStudy study={study.data} pairLabel={PAIRS[pair].label} focusBank={filter} />
      ) : (
        <EmptyState title={t("events.noStudy")}>{t("events.noStudyBody")}</EmptyState>
      )}

      {events.error ? (
        <ErrorState title={t("events.errEvents")} error={events.error} onRetry={events.reload} />
      ) : events.loading ? (
        <Loading label={t("events.loadingEvents")} height={320} />
      ) : (
        <div className="events-layout">
          <section className="card" aria-labelledby="upcoming-title">
            <h2 id="upcoming-title" className="card-title">
              {t("events.upcoming")}
            </h2>
            {upcoming.length ? (
              <ul className="upcoming" data-testid="upcoming-list">
                {upcoming.map((m) => (
                  <UpcomingRow key={`${m.bank}-${m.date}`} m={m} />
                ))}
              </ul>
            ) : (
              <EmptyState title={t("events.noUpcoming")} />
            )}
          </section>

          <section className="card" aria-labelledby="decisions-title">
            <h2 id="decisions-title" className="card-title">
              {t("events.past")}
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
              <EmptyState title={t("events.noDecisions")} />
            )}
          </section>
        </div>
      )}
    </div>
  );
}

function joinWords(items: string[]): string {
  return items.length < 2 ? items.join("") : t("fmt.list", { head: items.slice(0, -1).join(", "), last: items[items.length - 1] });
}

function UpcomingRow({ m }: { m: UpcomingMeeting }) {
  return (
    <li className="upcoming-row" data-bank={m.bank}>
      <span className="bank-tag">{BANK_LABELS[m.bank] ?? m.bank}</span>
      <time dateTime={m.date} className="upcoming-date">
        {fmtWeekdayDate(m.date)}
      </time>
      <span className="upcoming-until num">{fmtDaysUntil(m.days_until)}</span>
      {!m.scheduled && <span className="tag tag-warn">{t("events.unscheduled")}</span>}
    </li>
  );
}

function decisionVerb(d: DecisionOut): string {
  if (d.rate_before == null || d.rate_after == null) return t("events.decision");
  const bps = Math.round((d.rate_after - d.rate_before) * 100);
  if (bps === 0) return t("events.hold");
  return bps > 0 ? t("events.hike", { bps }) : t("events.cut", { bps: -bps });
}

function followedText(m: MeetingReactionOut): string | null {
  if (m.followed === true) return t("events.followedYes");
  if (m.followed === false) return t("events.followedNo");
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
  const vars = {
    pct: t("fmt.pct", { value: fmtNum(Math.abs(r), 2) }),
    end: signedPct(e),
    count: lastPoint.offset,
    n: lastPoint.offset,
  };
  if (Math.abs(r) < 0.05) return t("path.flat", vars);
  const dir = r < 0 ? "fell" : "rose";
  if (Math.sign(e) !== Math.sign(r) && Math.abs(e) >= 0.05) return t(`path.${dir}.reversed`, vars);
  if (Math.abs(e) > Math.abs(r) + 0.05) return t(`path.${dir}.kept`, vars);
  if (Math.abs(e) < Math.abs(r) - 0.05) return t(`path.${dir}.gave`, vars);
  return t(`path.${dir}.held`, vars);
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
  const label = `${t("events.around", { pair: pairLabel })}: ${sentence ?? ""}`;
  return (
    <div className="decision-move" data-testid="decision-move">
      <p className="decision-move-title">{t("events.around", { pair: pairLabel })}</p>
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
              <dt>{t("events.plusDays", { count: 5, n: 5 })}</dt>
              <dd className="num">{signedPct(at5.pct)}</dd>
            </div>
          )}
          {at10 && (
            <div>
              <dt>{t("events.plusDays", { count: 10, n: 10 })}</dt>
              <dd className="num">{signedPct(at10.pct)}</dd>
            </div>
          )}
        </dl>
      </div>
      {sentence && <p className="decision-move-sentence">{sentence}</p>}
      {followed && <p className="decision-move-note">{followed}</p>}
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
          <dt>{t("events.expected")}</dt>
          <dd className="num">
            {fmtPercentValue(d.expected, 3)}
            {d.expected_source && (
              <span className="cell-sub">{EXPECTED_SOURCE_LABELS[d.expected_source]?.() ?? d.expected_source}</span>
            )}
          </dd>
        </div>
        <div>
          <dt>{t("events.surprise")}</dt>
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
          <p>{d.hawkish_reason ?? t("events.notScored")}</p>
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
            {t("events.changes")}
            <span className="disclosure-count num">
              +{added.length} &minus;{removed.length}
            </span>
          </button>
        ) : (
          <span className="muted small">{t("events.noPrevious")}</span>
        )}
        {d.statement_url && (
          <a className="ext-link" href={d.statement_url} target="_blank" rel="noreferrer">
            {t("events.full")} <ExternalIcon size={13} />
          </a>
        )}
      </div>

      {diff && open && (
        <div id={diffId} className="diff" data-testid="statement-diff">
          {removed.length === 0 && added.length === 0 && <p className="muted small">{t("events.noChange")}</p>}
          {removed.map((s, i) => (
            <p key={`r${i}`} className="diff-line diff-removed">
              <span className="diff-mark" aria-label={t("events.removed")}>
                &minus;
              </span>
              <span>{s}</span>
            </p>
          ))}
          {added.map((s, i) => (
            <p key={`a${i}`} className="diff-line diff-added">
              <span className="diff-mark" aria-label={t("events.added")}>
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
