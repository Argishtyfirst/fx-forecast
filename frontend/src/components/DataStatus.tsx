import type { SourceStatus } from "../api/types";
import { SOURCE_LABELS, SOURCE_SHORT } from "../lib/constants";
import { fmtAgo, fmtCompactTime, fmtDateTime } from "../lib/format";
import { useHealth } from "../lib/health";
import { WarningIcon } from "./Icons";

interface DataStatusProps {
  /** Source keys that matter for this view. */
  relevant: string[];
  /** Stale sources reported by another response (the latest forecast carries stale_sources). */
  extraStale?: SourceStatus[];
}

const labelOf = (s: SourceStatus) => s.label || SOURCE_LABELS[s.source] || s.source;
const shortOf = (s: SourceStatus) => SOURCE_SHORT[s.source] ?? labelOf(s);

/**
 * FR-16 and the Frontend rule "each view shows the last update time per source":
 * a compact strip of sources with their last successful update, plus a warning for stale ones.
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

  return (
    <section className="data-status" aria-label="Data sources">
      {stale.length > 0 && <StaleWarning sources={stale} now={now} />}
      <div className="source-strip">
        <span className="source-strip-label">Last update</span>
        {ordered.length > 0 && (
          <ul className="source-list">
            {ordered.map((s) => (
              <li
                key={s.source}
                className={s.stale ? "source source-stale" : "source"}
                data-source={s.source}
                title={`${labelOf(s)}: last successful update ${fmtDateTime(s.last_success)}${
                  s.last_status ? `, last run ${s.last_status}` : ""
                }`}
              >
                <span className="source-dot" aria-hidden="true" />
                <span className="source-name">{shortOf(s)}</span>
                <time className="source-time num" dateTime={s.last_success ?? undefined}>
                  {fmtCompactTime(s.last_success, now)}
                </time>
                {s.stale && <span className="source-flag">stale</span>}
              </li>
            ))}
          </ul>
        )}
        {health?.error ? (
          <span className="source-missing">Source status unavailable: {health.error.message}</span>
        ) : ordered.length === 0 ? (
          <span className="source-missing">{health?.loading ? "Checking sources\u2026" : "No source status yet."}</span>
        ) : null}
      </div>
    </section>
  );
}

export function StaleWarning({ sources, now }: { sources: SourceStatus[]; now: Date }) {
  return (
    <div className="stale-warning" role="status" data-testid="stale-warning">
      <WarningIcon className="stale-icon" size={16} />
      <div>
        <p className="stale-title">
          Stale data from {sources.length === 1 ? "1 source" : `${sources.length} sources`}. Forecasts
          may use older inputs.
        </p>
        <ul className="stale-list">
          {sources.map((s) => (
            <li key={s.source} data-source={s.source} title={s.error ?? undefined}>
              <strong>{labelOf(s)}</strong>{" "}
              {s.last_success ? (
                <>
                  last successful update{" "}
                  <time dateTime={s.last_success} data-testid="stale-last-success">
                    {fmtDateTime(s.last_success)}
                  </time>{" "}
                  <span className="stale-ago">({fmtAgo(s.last_success, now)})</span>
                </>
              ) : (
                <>
                  last successful update{" "}
                  <span data-testid="stale-last-success">never</span>
                </>
              )}
              {s.error ? <span className="stale-error">. Last run failed: {s.error}</span> : "."}
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}
