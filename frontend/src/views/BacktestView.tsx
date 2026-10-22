import { api } from "../api/client";
import type { BacktestMetricOut, BacktestTargets, PairId } from "../api/types";
import { AiAnalysis, AiRecord, AroundMeetings } from "../components/BacktestExtras";
import { CoverageChart } from "../components/CoverageChart";
import { Disclaimer } from "../components/Disclaimer";
import { DataStatus } from "../components/DataStatus";
import { CheckIcon, CrossIcon } from "../components/Icons";
import { EmptyState, ErrorState, Loading } from "../components/States";
import { BAND_NOMINAL, HORIZONS, MODEL_LABELS, MODEL_ORDER, PAIR_SOURCES, PAIRS } from "../lib/constants";
import { fmtDate, fmtInt, fmtNum, fmtPct } from "../lib/format";
import { useApi } from "../lib/useApi";
import { t } from "../i18n";

type Verdict = "pass" | "fail" | "na";

const DEFAULT_TARGETS: BacktestTargets = {
  mae_ratio: 1.0,
  hit_rate: 0.5,
  coverage_tolerance: 0.05,
  dm_pvalue: 0.1,
  promotion_mae_ratio: 0.98,
};

interface BacktestViewProps {
  pair: PairId;
  window?: string;
  onWindow: (w: string) => void;
}

export function BacktestView({ pair, window: win, onWindow }: BacktestViewProps) {
  const meta = PAIRS[pair];
  const selected = win === "full" ? "full" : "250d";
  const bt = useApi(`backtests:${pair}`, () => Promise.all(HORIZONS.map((h) => api.backtests(pair, h.days))));
  const responses = (bt.data ?? []).filter((r): r is NonNullable<typeof r> => r !== null);
  const targets = responses[0]?.targets ?? DEFAULT_TARGETS;
  const runDate = responses.find((r) => r.run_date)?.run_date ?? null;
  const metrics = responses.flatMap((r) => r.metrics).filter((m) => m.window === selected);
  const allMetrics = responses.flatMap((r) => r.metrics);
  const eventMetrics = responses.flatMap((r) => r.event_metrics ?? []);
  const aiTrack = responses.flatMap((r) => r.ai_track ?? []);
  const analysis = responses.find((r) => r.ai_analysis)?.ai_analysis ?? null;
  const study = useApi(`meetings:${pair}`, () => api.meetings(pair, 365));

  return (
    <div className="view">
      <DataStatus relevant={PAIR_SOURCES[pair]} />
      <section className="view-head">
        <div>
          <h1 className="view-title">{t("bt.title")}</h1>
          <p className="view-sub">
            {t("bt.sub", { pair: meta.label })}
            {runDate && (
              <>
                {`${t("fmt.stop")} `}
                {t("bt.weekly")} <time dateTime={runDate}>{fmtDate(runDate)}</time>
              </>
            )}
          </p>
        </div>
        <div className="segmented" role="group" aria-label={t("bt.windowAria")}>
          {[
            { id: "250d", label: t("bt.last250") },
            { id: "full", label: t("bt.full") },
          ].map((w) => (
            <button
              key={w.id}
              type="button"
              className={selected === w.id ? "seg seg-active" : "seg"}
              aria-pressed={selected === w.id}
              onClick={() => onWindow(w.id)}
            >
              {w.label}
            </button>
          ))}
        </div>
      </section>

      <section className="targets" aria-label={t("bt.targetsAria")}>
        <p>
          <strong>{t("bt.targets")}</strong>{" "}
          {t("bt.targetsText", {
            tol: Math.round(targets.coverage_tolerance * 100),
            mae: fmtNum(targets.mae_ratio, 2),
            promo: fmtNum(targets.promotion_mae_ratio, 2),
            dm: fmtNum(targets.dm_pvalue, 2),
            hit: fmtPct(targets.hit_rate, 0),
          })}
        </p>
        <p className="verdict-key">
          <span className="verdict verdict-pass">
            <CheckIcon size={13} /> {t("bt.meets")}
          </span>
          <span className="verdict verdict-fail">
            <CrossIcon size={13} /> {t("bt.misses")}
          </span>
        </p>
      </section>

      {bt.error ? (
        <ErrorState title={t("bt.err")} error={bt.error} onRetry={bt.reload} />
      ) : bt.loading ? (
        <Loading label={t("bt.loading")} height={360} />
      ) : metrics.length === 0 ? (
        <EmptyState title={t("bt.empty")}>{t("bt.emptyBody")}</EmptyState>
      ) : (
        HORIZONS.map((h) => {
          const rows = metrics
            .filter((m) => m.horizon_days === h.days)
            .sort((a, b) => MODEL_ORDER.indexOf(a.model) - MODEL_ORDER.indexOf(b.model));
          if (!rows.length) return null;
          return (
            <HorizonBacktest
              key={h.days}
              label={h.label}
              long={h.long}
              rows={rows}
              targets={targets}
              window={selected}
            />
          );
        })
      )}

      {!bt.loading && !bt.error && responses.length > 0 && (
        <>
          <AroundMeetings
            pairLabel={meta.label}
            metrics={allMetrics}
            eventMetrics={eventMetrics}
            targets={targets}
            study={study.data ?? null}
          />
          <AiRecord rows={aiTrack} />
          <AiAnalysis analysis={analysis} />
          <Disclaimer />
        </>
      )}
    </div>
  );
}

function coverageVerdict(v: number, nominal: number, tol: number): Verdict {
  return Math.abs(v - nominal) <= tol + 1e-9 ? "pass" : "fail";
}

function HorizonBacktest({
  label,
  long,
  rows,
  targets,
  window,
}: {
  label: string;
  long: string;
  rows: BacktestMetricOut[];
  targets: BacktestTargets;
  window: string;
}) {
  const tol = targets.coverage_tolerance;
  const served = rows.find((r) => r.served);
  const span = rows[0];
  return (
    <section className="card bt-card" aria-labelledby={`bt-${label}`} data-testid={`backtest-${label}`}>
      <div className="card-head">
        <h2 id={`bt-${label}`} className="card-title">
          {label} <span className="card-title-sub">{long}</span>
        </h2>
        <p className="bt-span">
          {served && (
            <>
              {t("bt.servedLabel")} <strong>{MODEL_LABELS[served.model] ?? served.model}</strong> &middot;{" "}
            </>
          )}
          <span className="num">{t("bt.forecasts", { count: span.n_obs, n: fmtInt(span.n_obs) })}</span>
          {span.start_date && span.end_date && (
            <>
              {" "}
              &middot; {t("fmt.range", { lo: fmtDate(span.start_date), hi: fmtDate(span.end_date) })}
            </>
          )}
        </p>
      </div>
      <p className="scroll-hint">{t("bt.scroll")}</p>
      <div className="table-scroll">
        <table className="table bt-table">
          <thead>
            <tr>
              <th scope="col">{t("ranges.model")}</th>
              <th scope="col" className="num-col">
                n
              </th>
              <th scope="col" className="num-col">
                {t("bt.mae")}
                <span className="th-sub">&lt; {fmtNum(targets.mae_ratio, 2)}</span>
                <span className="th-sub">{t("bt.promote", { v: fmtNum(targets.promotion_mae_ratio, 2) })}</span>
              </th>
              <th scope="col" className="num-col">
                {t("bt.hit")}
                <span className="th-sub">&gt; {fmtPct(targets.hit_rate, 0)}</span>
              </th>
              <th scope="col" className="num-col">
                DM p
                <span className="th-sub">&lt; {fmtNum(targets.dm_pvalue, 2)}</span>
              </th>
              {(["50", "80", "95"] as const).map((b) => (
                <th key={b} scope="col" className="num-col">
                  {t("bt.cov", { level: b })}
                  <span className="th-sub">
                    {t("bt.covRange", { lo: Math.round((BAND_NOMINAL[b] - tol) * 100), hi: Math.round((BAND_NOMINAL[b] + tol) * 100) })}
                  </span>
                </th>
              ))}
              <th scope="col" className="num-col">
                {t("bt.pinball")}
                <span className="th-sub">{t("bt.vsGarch")}</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => {
              const isRw = r.model === "random_walk";
              return (
                <tr key={r.model} className={r.served ? "row-served" : undefined} data-model={r.model}>
                  <th scope="row">
                    <span className="model-cell">
                      <span className={`legend-dot model-${r.model}`} aria-hidden="true" />
                      {MODEL_LABELS[r.model] ?? r.model}
                    </span>
                    <span className="badges">
                      {r.served && <span className="tag tag-info">{t("drivers.servedTag")}</span>}
                      {r.promoted && <span className="tag tag-good">{t("bt.promoted")}</span>}
                      {isRw && <span className="tag">{t("bt.baseline")}</span>}
                    </span>
                  </th>
                  <td className="num num-col">{fmtInt(r.n_obs)}</td>
                  <Cell
                    value={fmtNum(r.mae_ratio_rw, 3)}
                    verdict={isRw ? "na" : r.mae_ratio_rw < targets.mae_ratio ? "pass" : "fail"}
                    note={
                      !isRw && window === "250d" && r.mae_ratio_rw < targets.promotion_mae_ratio
                        ? t("bt.below", { v: fmtNum(targets.promotion_mae_ratio, 2) })
                        : undefined
                    }
                  />
                  <Cell
                    value={r.hit_rate === null ? t("fmt.na") : fmtPct(r.hit_rate, 1)}
                    verdict={r.hit_rate === null ? "na" : r.hit_rate > targets.hit_rate ? "pass" : "fail"}
                  />
                  <Cell
                    value={r.dm_pvalue === null ? t("fmt.na") : fmtNum(r.dm_pvalue, 2)}
                    verdict={r.dm_pvalue === null ? "na" : r.dm_pvalue < targets.dm_pvalue ? "pass" : "fail"}
                  />
                  <Cell value={fmtPct(r.cov50, 1)} verdict={coverageVerdict(r.cov50, 0.5, tol)} />
                  <Cell value={fmtPct(r.cov80, 1)} verdict={coverageVerdict(r.cov80, 0.8, tol)} />
                  <Cell value={fmtPct(r.cov95, 1)} verdict={coverageVerdict(r.cov95, 0.95, tol)} />
                  <Cell
                    value={fmtNum(r.pinball, r.pinball < 0.01 ? 5 : 3)}
                    verdict={
                      r.pinball_ref === null || isRw ? "na" : r.pinball < r.pinball_ref ? "pass" : "fail"
                    }
                  />
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <CoverageChart metrics={rows} tolerance={tol} title={t("bt.covTitle", { label })} />
    </section>
  );
}

function Cell({ value, verdict, note }: { value: string; verdict: Verdict; note?: string }) {
  return (
    <td className={`num num-col cell-${verdict}`} data-verdict={verdict}>
      <span className="verdict-cell">
        {value}
        {verdict === "pass" && <CheckIcon size={13} className="verdict-icon" title={t("bt.meets")} />}
        {verdict === "fail" && <CrossIcon size={13} className="verdict-icon" title={t("bt.misses")} />}
      </span>
      {note && <span className="cell-sub">{note}</span>}
    </td>
  );
}
