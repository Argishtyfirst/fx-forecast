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
import { fmtDate, fmtDayMonth, fmtInt, fmtNum, fmtPct, na } from "../lib/format";
import { getLang, t as tr } from "../i18n";
import { CheckIcon, CrossIcon } from "./Icons";
import { ratioWord } from "./MeetingStudy";

const PROVIDER: Record<string, string> = { gemini: "Gemini" };
const period = (h: number) => tr(`around.period.${h === 1 ? "1D" : h === 5 ? "1W" : "1M"}` as "around.period.1D");

function Verdict({ ok }: { ok: boolean }) {
  return (
    <span className={ok ? "mark mark-pass" : "mark mark-miss"}>
      {ok ? <CheckIcon size={12} /> : <CrossIcon size={12} />}
      {ok ? tr("around.within") : tr("around.misses")}
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


/** One plain sentence: the bank whose meeting windows strain the served model's 80% range the most. */
function leadSentence(
  rows: EventWindowMetricOut[],
  served: (h: number) => string,
  lo: number,
  hi: number,
): string | null {
  const horizon = [5, 21, 1].find((h) => rows.some((r) => r.horizon_days === h && r.bank !== "none"));
  if (horizon === undefined) return null;
  const candidates = rows.filter((r) => r.horizon_days === horizon && r.bank !== "none" && r.model === served(horizon));
  if (!candidates.length) return null;
  const worst = [...candidates].sort((a, b) => Math.abs(b.cov80 - 0.8) - Math.abs(a.cov80 - 0.8))[0];
  const name = BANK_LABELS[worst.bank] ?? worst.bank;
  const pct = Math.round(worst.cov80 * 100);
  const vars = { lo: Math.round(lo * 100), hi: Math.round(hi * 100) };
  const verdict =
    worst.cov80 < lo - 1e-9
      ? tr("around.below", vars)
      : worst.cov80 > hi + 1e-9
        ? tr("around.above", vars)
        : tr("around.inside", vars);
  const h = horizon === 1 ? "1D" : horizon === 5 ? "1W" : "1M";
  return tr(`around.lead.${h}` as "around.lead.1D", { bank: name, pct, verdict });
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
  const lead = leadSentence(eventMetrics, served, lo, hi);

  return (
    <section className="card" aria-labelledby="around-title" data-testid="around-meetings">
      <div className="card-head">
        <h2 id="around-title" className="card-title">
          {tr("around.title")}
        </h2>
        <label className="toggle">
          <input type="checkbox" checked={allModels} onChange={(e) => setAllModels(e.target.checked)} />
          {tr("around.allModels")}
        </label>
      </div>

      {lead && (
        <p className="around-lead" data-testid="around-lead">
          {lead}
        </p>
      )}

      {study && study.banks.length > 0 && (
        <ul className="around-study">
          {study.banks.map((b) => (
            <li key={b.bank}>
              {b.reaction_ratio === null
                ? tr("around.moveUnknown", { bank: BANK_LABELS[b.bank] ?? b.bank, pair: pairLabel })
                : tr("around.move", { bank: BANK_LABELS[b.bank] ?? b.bank, pair: pairLabel, ratio: ratioWord(b.reaction_ratio) })}
              {b.n < 10 ? tr("around.small", { count: b.n, n: b.n }) : ""}
              {tr("fmt.stop")}
            </li>
          ))}
        </ul>
      )}

      {eventMetrics.length === 0 ? (
        <p className="muted small">{tr("around.empty")}</p>
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
                            const p = period(h.days);
                            const name = BANK_LABELS[r.bank] ?? r.bank;
                            return (
                              <li key={r.bank} className="around-row">
                                <span className="around-text">
                                  {tr("around.bandIn", { bank: name, period: p })}{" "}
                                  <span className="num">
                                    {fmtPct(r.cov80, 0)} ({tr("around.n", { n: fmtInt(r.n_obs) })})
                                  </span>
                                  {none && (
                                    <>
                                      {" "}
                                      {tr("around.vsOther", { period: p })}{" "}
                                      <span className="num">
                                        {fmtPct(none.cov80, 0)} ({tr("around.n", { n: fmtInt(none.n_obs) })})
                                      </span>
                                    </>
                                  )}
                                  <span className="around-sub">
                                    {tr("around.err", { value: fmtNum(r.mae_ratio_rw, 2) })}
                                    {none ? tr("around.errOther", { period: p, value: fmtNum(none.mae_ratio_rw, 2) }) : ""}
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
            <span className="covdots-key covdots-key-meeting" /> {tr("around.keyMeeting")}{" "}
            <span className="covdots-key covdots-key-other" /> {tr("around.keyOther")}{" "}
            <span className="covdots-key covdots-key-zone" /> {tr("around.keyTarget", { lo: Math.round(lo * 100), hi: Math.round(hi * 100) })}
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
        {tr("air.title")}
      </h2>
      {sorted.length === 0 || !version ? (
        <p className="ai-record-note">{tr("air.notRun")}</p>
      ) : !scored ? (
        <p className="ai-record-note">
          {tr("air.noneYet", { n: fmtInt(required), model: version })}
        </p>
      ) : (
        <div className="table-scroll">
          <table className="table">
            <thead>
              <tr>
                <th scope="col">{tr("air.horizon")}</th>
                <th scope="col" className="num-col">
                  {tr("air.scored")}
                </th>
                <th scope="col" className="num-col">
                  {tr("air.hit")}
                </th>
                <th scope="col" className="num-col">
                  {tr("air.brier")}
                  <span className="th-sub">{tr("air.coin", { value: fmtNum(0.25, 2) })}</span>
                </th>
                <th scope="col" className="num-col">
                  {tr("air.errRw")}
                </th>
                <th scope="col">{tr("air.status")}</th>
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
                      {tr("air.of", { done: fmtInt(t.n_scored), total: fmtInt(t.required) })}
                    </td>
                    <td className="num num-col">{t.hit_rate === null ? na() : fmtPct(t.hit_rate, 1)}</td>
                    <td className="num num-col">{t.brier === null ? na() : fmtNum(t.brier, 3)}</td>
                    <td className="num num-col">{t.mae_ratio_rw === null ? na() : fmtNum(t.mae_ratio_rw, 3)}</td>
                    <td>{t.promoted ? <span className="tag tag-info">{tr("air.proven")}</span> : tr("air.unproven")}</td>
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

/** Bold the numbers in a sentence (tabular figures), so a scan picks them up first. */
function withNumbers(text: string) {
  // Bold figures, not the digits inside words such as "1-week" or "1W".
  const parts = text.split(/(?<![\w.-])(\d+(?:\.\d+)?(?:%| times|x)?)(?![\w-])/g);
  return parts.map((part, i) =>
    i % 2 === 1 ? (
      <strong key={i} className="num">
        {part}
      </strong>
    ) : (
      part
    ),
  );
}

const MONTHS = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"];
const CHIP_BANK: Record<string, string> = { Fed: "FED", ECB: "ECB", CBA: "CBA" };

/** Meeting chips from text like "The Fed on 28 Oct" or "Fed and ECB decide on 28 and 29 October". */
export function meetingChips(text: string): string[] {
  const banks = [...text.matchAll(/\b(Fed|FOMC|ECB|CBA)\b/g)].map(
    (m) => BANK_LABELS[CHIP_BANK[m[1] === "FOMC" ? "Fed" : m[1]]] ?? m[1],
  );
  const day = (d: string, mon: number) => fmtDayMonth(Number(d), mon);
  const dates: string[] = [];
  for (const m of text.matchAll(/\b(\d{1,2})(?:\s+and\s+(\d{1,2}))?\s+(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\b/gi)) {
    const mon = MONTHS.indexOf(m[3].toLowerCase());
    dates.push(day(m[1], mon));
    if (m[2]) dates.push(day(m[2], mon));
  }
  if (!dates.length) return [];
  const uniqueBanks = [...new Set(banks)];
  if (uniqueBanks.length === dates.length) return dates.map((d, i) => `${uniqueBanks[i]} ${d}`);
  if (uniqueBanks.length === 1) return dates.map((d) => `${uniqueBanks[0]} ${d}`);
  return dates;
}

/** "AI analysis": Gemini's weekly written reading, built for a five-second read. */
export function AiAnalysis({ analysis }: { analysis: AiAnalysisOut | null }) {
  const lang = getLang();
  const local = lang === "en" ? undefined : analysis?.i18n?.[lang];
  const points = local?.points?.length ? local.points : (analysis?.points ?? []);
  return (
    <section className="card ai-analysis" aria-labelledby="ai-analysis-title" data-testid="ai-analysis">
      <h2 id="ai-analysis-title" className="card-title">
        {tr("aia.title")}
      </h2>
      {!analysis ? (
        <p className="ai-record-note">{tr("aia.empty")}</p>
      ) : (
        <>
          <p className="ai-byline">
            {tr("aia.byline", {
              name: PROVIDER[analysis.provider] ?? analysis.provider,
              model: analysis.model,
              date: fmtDate(analysis.run_date),
            })}
          </p>
          <p className="ai-takeaway" data-testid="ai-takeaway">
            {withNumbers(local?.headline || analysis.headline)}
          </p>
          {analysis.for_you && (
            <p className="ai-for-you" data-testid="ai-for-you">
              <span className="ai-for-you-label">{tr("aia.forYou")}</span> {local?.for_you || analysis.for_you}
            </p>
          )}
          {points.length > 0 && (
            <ul className="ai-bullets">
              {points.slice(0, 3).map((p) => (
                <li key={p}>{withNumbers(p)}</li>
              ))}
            </ul>
          )}
          {analysis.watch_next && (
            <div className="ai-watch">
              <span className="ai-watch-label">{tr("aia.watch")}</span>
              {meetingChips(analysis.watch_next).length > 0 && (
                <span className="ai-watch-chips">
                  {meetingChips(analysis.watch_next).map((c) => (
                    <span key={c} className="bank-chip">
                      {c}
                    </span>
                  ))}
                </span>
              )}
              <span className="ai-watch-text">{local?.watch_next || analysis.watch_next}</span>
            </div>
          )}
        </>
      )}
    </section>
  );
}
