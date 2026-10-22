import type { SourceStatus } from "../api/types";
import { SOURCE_LABELS, SOURCE_SHORT } from "../lib/constants";
import { fmtAgo, fmtCompactTime, fmtDateTime } from "../lib/format";
import { useHealth } from "../lib/health";
import { WarningIcon } from "./Icons";
import { t } from "../i18n";

interface DataStatusProps {
  /** Source keys that matter for this view. */
  relevant: string[];
  /** Stale sources reported by another response (the latest forecast carries stale_sources). */
  extraStale?: SourceStatus[];
}

// The API's labels are English; the translated name wins when there is one.
const labelOf = (s: SourceStatus) => SOURCE_LABELS[s.source] ?? (s.label || s.source);
const shortOf = (s: SourceStatus) => SOURCE_SHORT[s.source] ?? labelOf(s);

/**
 * FR-16 and "each view shows the last update time per source": one quiet line with the latest
 * update and a Details disclosure listing every source, plus one compact line only when
 * something is stale (naming the source and its last successful update).
 */
export function DataStatus({ relevant, extraStale = [] }: DataStatusProps) {
  const health = useHealth();
  const data = health?.data;
  const now = data ? new Date(data.checked_at) : new Date();

  const fromHealth = (data?.sources ?? []).filter((s) => relevant.includes(s.source));
  const known = new Set(fromHealth.map((s) => s.source));
  // Health is fresher; the forecast's list fills in when health is unavailable.
  const merged = [
    ...fromHealth,
    ...extraStale.filter((s) => !known.has(s.source) && relevant.includes(s.source)),
  ];
  const ordered = relevant
    .map((key) => merged.find((s) => s.source === key))
    .filter((s): s is SourceStatus => Boolean(s));
  const stale = ordered.filter((s) => s.stale);
  const latest = ordered
    .map((s) => s.last_success)
    .filter((t): t is string => Boolean(t))
    .sort()
    .pop();

  let summary: string;
  if (health?.error && ordered.length === 0) summary = t("status.unavailable", { error: health.error.message });
  else if (ordered.length === 0) summary = health?.loading ? t("status.checking") : t("status.none");
  else
    summary = t("status.summary", {
      time: fmtCompactTime(latest, now),
      state:
        stale.length === 0
          ? t("status.allCurrent")
          : t("status.someStale", { count: stale.length, stale: stale.length, total: ordered.length }),
    });

  return (
    <section className="data-status" aria-label={t("status.aria")}>
      <details className="data-line">
        <summary>
          <span data-testid="data-summary">{summary}</span>
          {ordered.length > 0 && <span className="data-more">{t("status.details")}</span>}
        </summary>
        {health?.error && ordered.length > 0 && (
          <p className="source-missing">{t("status.unavailable", { error: health.error.message })}</p>
        )}
        <ul className="source-list" data-testid="source-list">
          {ordered.map((s) => (
            <li key={s.source} data-source={s.source} className={s.stale ? "source source-stale" : "source"}>
              <span className="source-name">{labelOf(s)}</span>
              <time className="source-time num" dateTime={s.last_success ?? undefined}>
                {fmtCompactTime(s.last_success, now)}
              </time>
              <span className="source-state">
                {s.stale ? (s.error ? t("status.staleWith", { error: s.error }) : t("status.stale")) : t("status.current")}
              </span>
            </li>
          ))}
        </ul>
      </details>
      {stale.length > 0 && <StaleWarning sources={stale} now={now} />}
    </section>
  );
}

export function StaleWarning({ sources, now }: { sources: SourceStatus[]; now: Date }) {
  return (
    <p className="stale-line" role="status" data-testid="stale-warning">
      <WarningIcon className="stale-icon" size={14} />
      <span>
        <span className="stale-title">{t("status.staleTitle")} </span>
        {sources.map((s, i) => (
          <span key={s.source} data-source={s.source} title={s.error ?? undefined}>
            <strong>{shortOf(s)}</strong>
            {s.last_success ? (
              <>
                {t("status.lastSuccess")}{" "}
                <time dateTime={s.last_success} data-testid="stale-last-success">
                  {fmtDateTime(s.last_success)}
                </time>{" "}
                <span className="stale-ago">({fmtAgo(s.last_success, now)})</span>
              </>
            ) : (
              <>
                {t("status.lastSuccess")} <span data-testid="stale-last-success">{t("fmt.never")}</span>
              </>
            )}
            {i < sources.length - 1 ? "; " : "."}
          </span>
        ))}
      </span>
    </p>
  );
}
