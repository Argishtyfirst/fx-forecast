import { api } from "../api/client";
import type { BacktestMetricOut, BacktestTargets, PairId } from "../api/types";
import { CoverageChart } from "../components/CoverageChart";
import { DataStatus } from "../components/DataStatus";
import { CheckIcon, CrossIcon } from "../components/Icons";
import { EmptyState, ErrorState, Loading } from "../components/States";
import { BAND_NOMINAL, HORIZONS, MODEL_LABELS, MODEL_ORDER, PAIR_SOURCES, PAIRS } from "../lib/constants";
import { fmtDate, fmtInt, fmtNum, fmtPct } from "../lib/format";
import { useApi } from "../lib/useApi";

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

  return (
    <div className="view">
      <DataStatus relevant={PAIR_SOURCES[pair]} />
      <section className="view-head">
        <div>
          <h1 className="view-title">Backtest</h1>
          <p className="view-sub">
            {meta.label} &middot; walk-forward against the random walk
            {runDate && (
              <>
                {" "}
                &middot; weekly run <time dateTime={runDate}>{fmtDate(runDate)}</time>
              </>
            )}
          </p>
        </div>
        <div className="segmented" role="group" aria-label="Backtest window">
          {[
            { id: "250d", label: "Last 250 days" },
            { id: "full", label: "Full history" },
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

      <section className="targets" aria-label="Targets">
        <p>
          <strong>Targets.</strong> Band coverage within &plusmn;{Math.round(targets.coverage_tolerance * 100)} points of
          nominal. MAE ratio below {fmtNum(targets.mae_ratio, 2)}; a model is promoted below{" "}
          {fmtNum(targets.promotion_mae_ratio, 2)} with a Diebold-Mariano p-value below {fmtNum(targets.dm_pvalue, 2)} over
          250 days. Directional hit rate above {fmtPct(targets.hit_rate, 0)}.
        </p>
        <p className="verdict-key">
          <span className="verdict verdict-pass">
            <CheckIcon size={13} /> meets target
          </span>
          <span className="verdict verdict-fail">
            <CrossIcon size={13} /> misses target
          </span>
        </p>
      </section>

      {bt.error ? (
        <ErrorState title="Could not load the backtest" error={bt.error} onRetry={bt.reload} />
      ) : bt.loading ? (
        <Loading label="Loading backtest metrics" height={360} />
      ) : metrics.length === 0 ? (
        <EmptyState title="No backtest yet">The weekly walk-forward run stores metrics per pair, horizon and model.</EmptyState>
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
              Served: <strong>{MODEL_LABELS[served.model] ?? served.model}</strong> &middot;{" "}
            </>
          )}
          <span className="num">{fmtInt(span.n_obs)}</span> forecasts
          {span.start_date && span.end_date && (
            <>
              {" "}
              &middot; {fmtDate(span.start_date)} to {fmtDate(span.end_date)}
            </>
          )}
        </p>
      </div>
      <p className="scroll-hint">Scroll the table sideways for every metric.</p>
      <div className="table-scroll">
        <table className="table bt-table">
          <thead>
            <tr>
              <th scope="col">Model</th>
              <th scope="col" className="num-col">
                n
              </th>
              <th scope="col" className="num-col">
                MAE ratio
                <span className="th-sub">&lt; {fmtNum(targets.mae_ratio, 2)}</span>
                <span className="th-sub">promote &lt; {fmtNum(targets.promotion_mae_ratio, 2)}</span>
              </th>
              <th scope="col" className="num-col">
                Hit rate
                <span className="th-sub">&gt; {fmtPct(targets.hit_rate, 0)}</span>
              </th>
              <th scope="col" className="num-col">
                DM p
                <span className="th-sub">&lt; {fmtNum(targets.dm_pvalue, 2)}</span>
              </th>
              {(["50", "80", "95"] as const).map((b) => (
                <th key={b} scope="col" className="num-col">
                  Cov {b}%
                  <span className="th-sub">
                    {Math.round((BAND_NOMINAL[b] - tol) * 100)}&ndash;{Math.round((BAND_NOMINAL[b] + tol) * 100)}%
                  </span>
                </th>
              ))}
              <th scope="col" className="num-col">
                Pinball
                <span className="th-sub">vs GARCH</span>
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
                      {r.served && <span className="tag tag-info">Served</span>}
                      {r.promoted && <span className="tag tag-good">Promoted</span>}
                      {isRw && <span className="tag">Baseline</span>}
                    </span>
                  </th>
                  <td className="num num-col">{fmtInt(r.n_obs)}</td>
                  <Cell
                    value={fmtNum(r.mae_ratio_rw, 3)}
                    verdict={isRw ? "na" : r.mae_ratio_rw < targets.mae_ratio ? "pass" : "fail"}
                    note={
                      !isRw && window === "250d" && r.mae_ratio_rw < targets.promotion_mae_ratio
                        ? `below ${fmtNum(targets.promotion_mae_ratio, 2)}`
                        : undefined
                    }
                  />
                  <Cell
                    value={r.hit_rate === null ? "—" : fmtPct(r.hit_rate, 1)}
                    verdict={r.hit_rate === null ? "na" : r.hit_rate > targets.hit_rate ? "pass" : "fail"}
                  />
                  <Cell
                    value={r.dm_pvalue === null ? "—" : fmtNum(r.dm_pvalue, 2)}
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
      <CoverageChart metrics={rows} tolerance={tol} title={`${label} band coverage against nominal`} />
    </section>
  );
}

function Cell({ value, verdict, note }: { value: string; verdict: Verdict; note?: string }) {
  return (
    <td className={`num num-col cell-${verdict}`} data-verdict={verdict}>
      <span className="verdict-cell">
        {value}
        {verdict === "pass" && <CheckIcon size={13} className="verdict-icon" title="meets target" />}
        {verdict === "fail" && <CrossIcon size={13} className="verdict-icon" title="misses target" />}
      </span>
      {note && <span className="cell-sub">{note}</span>}
    </td>
  );
}
