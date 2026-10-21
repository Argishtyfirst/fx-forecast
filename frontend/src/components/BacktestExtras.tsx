import { useState } from "react";
import type {
  AiAnalysisOut,
  AiTrackRow,
  BacktestMetricOut,
  BacktestTargets,
  EventWindowMetricOut,
  MeetingStudyResponse,
} from "../api/types";
import { BANK_LABELS, HORIZONS, MODEL_LABELS, MODEL_ORDER } from "../lib/constants";
import { fmtDate, fmtInt, fmtNum, fmtPct } from "../lib/format";
import { CheckIcon, CrossIcon } from "./Icons";
import { ratioWord } from "./MeetingStudy";

const PERIOD: Record<number, string> = { 1: "days", 5: "weeks", 21: "months" };
const PROVIDER: Record<string, string> = { gemini: "Gemini" };

function Verdict({ ok }: { ok: boolean }) {
  return (
    <span className={ok ? "mark mark-pass" : "mark mark-miss"}>
      {ok ? <CheckIcon size={12} /> : <CrossIcon size={12} />}
      {ok ? "within target" : "misses target"}
    </span>
  );
}

/** Where coverage sits on a 60 to 100% scale, with the 75 to 85% target shaded. */
function CoverageDots({ meeting, other }: { meeting: number; other: number | null }) {
  const pos = (v: number) => `${Math.max(0, Math.min(1, (v - 0.6) / 0.4)) * 100}%`;
  return (
    <span className="covdots" aria-hidden="true">
      <span className="covdots-zone" style={{ left: pos(0.75), width: `${(0.1 / 0.4) * 100}%` }} />
      {other !== null && <span className="covdots-other" style={{ left: pos(other) }} />}
      <span className="covdots-meeting" style={{ left: pos(meeting) }} />
    </span>
  );
}

/** "Around meetings, last 12 months": 80% band coverage and error with a meeting inside vs without. */
export function AroundMeetings({
  pairLabel,
  metrics,
  eventMetrics,
  targets,
  study,
}: {
  pairLabel: string;
  metrics: BacktestMetricOut[];
  eventMetrics: EventWindowMetricOut[];
  targets: BacktestTargets;
  study: MeetingStudyResponse | null;
}) {
  const [allModels, setAllModels] = useState(false);
  const tol = targets.coverage_tolerance;
  const lo = 0.8 - tol;
  const hi = 0.8 + tol;
  const served = (h: number) => metrics.find((m) => m.horizon_days === h && m.window === "250d" && m.served)?.model ?? "random_walk";

  return (
    <section className="card" aria-labelledby="around-title" data-testid="around-meetings">
      <div className="card-head">
        <h2 id="around-title" className="card-title">
          Around meetings, last 12 months
        </h2>
        <label className="toggle">
          <input type="checkbox" checked={allModels} onChange={(e) => setAllModels(e.target.checked)} />
          Show all models
        </label>
      </div>

      {study && study.banks.length > 0 && (
        <ul className="around-study">
          {study.banks.map((b) => (
            <li key={b.bank}>
              {BANK_LABELS[b.bank] ?? b.bank} meetings move {pairLabel}{" "}
              {b.reaction_ratio === null ? "by an unknown amount" : `${ratioWord(b.reaction_ratio)} a normal day`}
              {b.n < 10 ? ` (small sample, ${b.n} meetings)` : ""}.
            </li>
          ))}
        </ul>
      )}

      {eventMetrics.length === 0 ? (
        <p className="muted small">The around-meetings split appears after the next weekly backtest.</p>
      ) : (
        <div className="around-grid">
          {HORIZONS.map((h) => {
            const models = [...new Set(eventMetrics.filter((m) => m.horizon_days === h.days).map((m) => m.model))]
              .filter((m) => allModels || m === served(h.days))
              .sort((a, b) => MODEL_ORDER.indexOf(a) - MODEL_ORDER.indexOf(b));
            if (!models.length) return null;
            return (
              <div key={h.days} className="around-horizon" data-testid={`around-${h.label}`}>
                <p className="around-h">
                  <span className="around-label">{h.label}</span> {h.long}
                </p>
                {models.map((model) => {
                  const rows = eventMetrics.filter((m) => m.horizon_days === h.days && m.model === model);
                  const none = rows.find((r) => r.bank === "none") ?? null;
                  return (
                    <div key={model} className="around-model">
                      {allModels && <p className="around-modelname">{MODEL_LABELS[model] ?? model}</p>}
                      <ul>
                        {rows
                          .filter((r) => r.bank !== "none")
                          .map((r) => {
                            const p = PERIOD[h.days];
                            const name = BANK_LABELS[r.bank] ?? r.bank;
                            return (
                              <li key={r.bank} className="around-row">
                                <span className="around-text">
                                  80% band in {name} {p}:{" "}
                                  <span className="num">
                                    {fmtPct(r.cov80, 0)} (n {fmtInt(r.n_obs)})
                                  </span>
                                  {none && (
                                    <>
                                      {" "}
                                      vs other {p}:{" "}
                                      <span className="num">
                                        {fmtPct(none.cov80, 0)} (n {fmtInt(none.n_obs)})
                                      </span>
                                    </>
                                  )}
                                  <span className="around-sub">
                                    Error vs random walk {fmtNum(r.mae_ratio_rw, 2)}
                                    {none ? `, other ${p} ${fmtNum(none.mae_ratio_rw, 2)}` : ""}
                                  </span>
                                </span>
                                <CoverageDots meeting={r.cov80} other={none?.cov80 ?? null} />
                                <Verdict ok={r.cov80 >= lo - 1e-9 && r.cov80 <= hi + 1e-9} />
                              </li>
                            );
                          })}
                      </ul>
                    </div>
                  );
                })}
              </div>
            );
          })}
          <p className="around-key">
            <span className="covdots-key covdots-key-meeting" /> meeting {""}
            <span className="covdots-key covdots-key-other" /> other {""}
            <span className="covdots-key covdots-key-zone" /> target {Math.round(lo * 100)} to {Math.round(hi * 100)}%
          </p>
        </div>
      )}
    </section>
  );
}

/** "AI view, live record": next to the statistical models, scored only on dates that have passed. */
export function AiRecord({ rows }: { rows: AiTrackRow[] }) {
  const sorted = [...rows].sort((a, b) => a.horizon_days - b.horizon_days);
  const scored = sorted.some((r) => r.track_record.n_scored > 0);
  const version = sorted.find((r) => r.model_version)?.model_version ?? null;
  const required = sorted[0]?.track_record.required ?? 250;
  return (
    <section className="card" aria-labelledby="ai-record-title" data-testid="ai-record">
      <h2 id="ai-record-title" className="card-title">
        AI view, live record
      </h2>
      {sorted.length === 0 || !version ? (
        <p className="ai-record-note">The AI view has not run yet for this pair.</p>
      ) : !scored ? (
        <p className="ai-record-note">
          No AI forecasts have reached their date yet; the first 1-day checks arrive tomorrow. Each horizon needs{" "}
          {fmtInt(required)} scored forecasts before the AI view can be promoted. Model {version}.
        </p>
      ) : (
        <div className="table-scroll">
          <table className="table">
            <thead>
              <tr>
                <th scope="col">Horizon</th>
                <th scope="col" className="num-col">
                  Scored
                </th>
                <th scope="col" className="num-col">
                  Hit rate
                </th>
                <th scope="col" className="num-col">
                  Brier
                  <span className="th-sub">0.25 = coin flip</span>
                </th>
                <th scope="col" className="num-col">
                  Error vs random walk
                </th>
                <th scope="col">Status</th>
              </tr>
            </thead>
            <tbody>
              {sorted.map((r) => {
                const t = r.track_record;
                const label = HORIZONS.find((h) => h.days === r.horizon_days)?.label ?? `${r.horizon_days}D`;
                return (
                  <tr key={r.horizon_days}>
                    <th scope="row">{label}</th>
                    <td className="num num-col">
                      {fmtInt(t.n_scored)} of {fmtInt(t.required)}
                    </td>
                    <td className="num num-col">{t.hit_rate === null ? "n/a" : fmtPct(t.hit_rate, 1)}</td>
                    <td className="num num-col">{t.brier === null ? "n/a" : fmtNum(t.brier, 3)}</td>
                    <td className="num num-col">{t.mae_ratio_rw === null ? "n/a" : fmtNum(t.mae_ratio_rw, 3)}</td>
                    <td>{t.promoted ? <span className="tag tag-info">Proven</span> : "Not yet proven"}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

/** "AI analysis": Gemini's weekly written reading. Text, not a forecast. */
export function AiAnalysis({ analysis }: { analysis: AiAnalysisOut | null }) {
  return (
    <section className="card" aria-labelledby="ai-analysis-title" data-testid="ai-analysis">
      <h2 id="ai-analysis-title" className="card-title">
        AI analysis
      </h2>
      {!analysis ? (
        <p className="ai-record-note">The weekly AI analysis appears after the next weekly run.</p>
      ) : (
        <>
          <p className="ai-byline">
            Written by {PROVIDER[analysis.provider] ?? analysis.provider} ({analysis.model}), experimental,{" "}
            {fmtDate(analysis.run_date)}
          </p>
          <p className="ai-headline-text">{analysis.headline}</p>
          <div className="ai-points">
            {analysis.points.map((p) => (
              <p key={p}>{p}</p>
            ))}
          </div>
          <p className="ai-watch">
            <span className="ai-watch-label">Watch next.</span> {analysis.watch_next}
          </p>
        </>
      )}
    </section>
  );
}
