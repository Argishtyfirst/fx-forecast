import { useState } from "react";
import { api } from "../api/client";
import type { ForecastRow, HorizonForecast, PairId } from "../api/types";
import { DataStatus } from "../components/DataStatus";
import { Disclaimer } from "../components/Disclaimer";
import { HawkishScale } from "../components/HawkishScale";
import { EmptyState, ErrorState, Loading } from "../components/States";
import { BANK_LABELS, BANK_LONG, HORIZONS, MODEL_LABELS, MODEL_ORDER, PAIR_SOURCES, PAIRS } from "../lib/constants";
import {
  fmtBps,
  fmtDate,
  fmtDaysUntil,
  fmtNum,
  fmtPct,
  fmtPercentValue,
  fmtRange,
  fmtRate,
  fmtShortDate,
  fmtSigned,
} from "../lib/format";
import { useApi } from "../lib/useApi";
import { getLang, t } from "../i18n";

interface DriversViewProps {
  pair: PairId;
  horizon?: string;
  onHorizon: (label: string) => void;
}

export function DriversView({ pair, horizon, onHorizon }: DriversViewProps) {
  const meta = PAIRS[pair];
  const latest = useApi(`latest:${pair}`, () => api.latestForecast(pair));
  const forecast = latest.data ?? null;
  const selected = HORIZONS.find((h) => h.label === horizon)?.label ?? "1M";
  const h = forecast?.horizons.find((x) => x.label === selected);

  return (
    <div className="view">
      <DataStatus relevant={PAIR_SOURCES[pair]} extraStale={forecast?.stale_sources} />
      <section className="view-head">
        <div>
          <h1 className="view-title">{t("drivers.title")}</h1>
          <p className="view-sub">
            {t("drivers.sub", { pair: meta.label })}
            {forecast && (
              <>
                {`${t("fmt.stop")} `}
                {t("drivers.run")} <time dateTime={forecast.as_of}>{fmtDate(forecast.as_of)}</time>
              </>
            )}
          </p>
        </div>
        <div className="segmented" role="group" aria-label={t("drivers.horizonAria")}>
          {HORIZONS.map((x) => (
            <button
              key={x.label}
              type="button"
              className={x.label === selected ? "seg seg-active" : "seg"}
              aria-pressed={x.label === selected}
              onClick={() => onHorizon(x.label)}
            >
              {x.label}
            </button>
          ))}
        </div>
      </section>

      {latest.error ? (
        <ErrorState title={t("drivers.err")} error={latest.error} onRetry={latest.reload} />
      ) : latest.loading ? (
        <Loading label={t("drivers.loading")} height={360} />
      ) : !forecast ? (
        <EmptyState title={t("pair.noForecast")}>{t("drivers.emptyBody")}</EmptyState>
      ) : !h ? (
        <EmptyState title={t("drivers.noHorizon", { label: selected })} />
      ) : (
        <>
          <ServedSummary horizons={forecast.horizons} selected={selected} onSelect={onHorizon} />
          <DriverPanels pair={pair} h={h} spot={forecast.spot} />
          <Candidates
            pair={pair}
            runDate={forecast.as_of}
            horizonDays={h.days}
            decimals={meta.decimals}
            disclaimer={forecast.disclaimer}
          />
        </>
      )}
    </div>
  );
}

/** Why the model is served: the API's reason in English; a translated summary otherwise. */
function servedReason(h: HorizonForecast): string {
  const reason = h.drivers.served_reason;
  if (getLang() === "en") return reason ?? t("drivers.noReason");
  return h.model === "random_walk" ? t("drivers.reasonRw") : t("drivers.reasonPromoted", { model: MODEL_LABELS[h.model] ?? h.model });
}

function ServedSummary({
  horizons,
  selected,
  onSelect,
}: {
  horizons: HorizonForecast[];
  selected: string;
  onSelect: (label: string) => void;
}) {
  const sorted = [...horizons].sort((a, b) => a.days - b.days);
  return (
    <section className="card" aria-labelledby="served-title">
      <h2 id="served-title" className="card-title">
        {t("drivers.served")}
      </h2>
      <ul className="served-list">
        {sorted.map((h) => (
          <li key={h.days} className={h.label === selected ? "served-row served-row-active" : "served-row"}>
            <button type="button" className="served-horizon" onClick={() => onSelect(h.label)} aria-pressed={h.label === selected}>
              {h.label}
            </button>
            <div className="served-body">
              <p className="served-model">
                {MODEL_LABELS[h.model] ?? h.model}
                <span className="served-version">{h.model_version}</span>
              </p>
              <p className="served-reason">{servedReason(h)}</p>
            </div>
          </li>
        ))}
      </ul>
    </section>
  );
}

function DriverPanels({ pair, h, spot }: { pair: PairId; h: HorizonForecast; spot: number }) {
  const meta = PAIRS[pair];
  const d = h.drivers;
  const banks = meta.banks;
  const extra = d.event_extra_variance ?? 0;
  const sigma = d.horizon_sigma ?? null;
  const widened = extra > 0 && sigma !== null;
  const widening = widened ? sigma / Math.sqrt(Math.max(sigma * sigma - extra, 1e-18)) - 1 : 0;
  const fwdVsSpot = d.forward_rate != null ? d.forward_rate / spot - 1 : null;

  return (
    <div className={`bento bento-banks-${banks.length}`}>
      <section className="card metric-card" aria-labelledby="diff-title">
        <h2 id="diff-title" className="card-title">
          {t("drivers.diff")}
        </h2>
        <p className="metric-value num" data-testid="rate-diff">
          {fmtBps(d.rate_diff_bps)}
        </p>
        <p className="metric-note">{t("drivers.diffNote", { diff: meta.diffLabel })}</p>
        <dl className="kv">
          <div>
            <dt>{t("drivers.change21")}</dt>
            <dd className="num">{fmtBps(d.rate_diff_change_21d_bps)}</dd>
          </div>
          {banks.map((b) => (
            <div key={b}>
              <dt>{t("drivers.policyRate", { bank: BANK_LABELS[b] ?? b })}</dt>
              <dd className="num">{fmtPercentValue(d.policy_rates?.[b], 3)}</dd>
            </div>
          ))}
        </dl>
      </section>

      <section className="card metric-card" aria-labelledby="fwd-title">
        <h2 id="fwd-title" className="card-title">
          {t("drivers.forward")} &middot; {h.label}
        </h2>
        <p className="metric-value num" data-testid="forward-rate">
          {fmtRate(d.forward_rate, meta.decimals + 1)}
        </p>
        <p className="metric-note">{t("drivers.forwardNote")}</p>
        <dl className="kv">
          <div>
            <dt>{t("fan.spot")}</dt>
            <dd className="num">{fmtRate(spot, meta.decimals)}</dd>
          </div>
          <div>
            <dt>{t("drivers.fwdVsSpot")}</dt>
            <dd className="num">{fwdVsSpot === null ? t("fmt.na") : t("fmt.pct", { value: fmtSigned(fwdVsSpot * 100, 2) })}</dd>
          </div>
        </dl>
      </section>

      <section className="card metric-card" aria-labelledby="vol-title">
        <h2 id="vol-title" className="card-title">
          {t("drivers.vol")} &middot; {h.label}
        </h2>
        <p className="metric-value num" data-testid="garch-vol">
          {fmtPct(d.garch_vol_annual, 1)}
        </p>
        <p className="metric-note">{t("drivers.volNote")}</p>
        <dl className="kv">
          <div>
            <dt>{t("drivers.sigma")}</dt>
            <dd className="num">{sigma === null ? t("fmt.na") : t("fmt.pct", { value: fmtNum(sigma * 100, 2) })}</dd>
          </div>
          <div>
            <dt>{t("drivers.widening")}</dt>
            <dd data-testid="event-widening">
              {widened ? (
                <>
                  <span className="tag tag-info">{t("drivers.widened")}</span>{" "}
                  <span className="num">{t("drivers.width", { pct: fmtSigned(widening * 100, 1) })}</span>
                </>
              ) : (
                <span className="muted">{t("ranges.none")}</span>
              )}
            </dd>
          </div>
          {widened && (
            <div>
              <dt>{t("drivers.extraVar")}</dt>
              <dd className="num mono-small">{extra.toExponential(2)}</dd>
            </div>
          )}
          {h.meetings.length > 0 && (
            <div>
              <dt>{t("drivers.forMeetings")}</dt>
              <dd>
                {h.meetings.map((m) => `${BANK_LABELS[m.bank] ?? m.bank} ${fmtShortDate(m.date)}`).join(", ")}
              </dd>
            </div>
          )}
        </dl>
      </section>

      {banks.map((b) => (
        <section key={b} className="card metric-card bank-card" aria-labelledby={`bank-${b}`} data-testid={`bank-card-${b}`}>
          <h2 id={`bank-${b}`} className="card-title">
            <span className="bank-tag">{BANK_LABELS[b]}</span> {BANK_LONG[b]}
          </h2>
          <dl className="kv">
            <div>
              <dt>{t("drivers.lastSurprise")}</dt>
              <dd className="num">{fmtBps(d.last_surprise_bps?.[b])}</dd>
            </div>
            <div>
              <dt>{t("drivers.nextMeeting")}</dt>
              <dd className="num">{fmtDaysUntil(d.days_to_next_meeting?.[b])}</dd>
            </div>
          </dl>
          <p className="kv-label">{t("drivers.hawkish")}</p>
          <HawkishScale score={d.hawkish_score?.[b]} />
        </section>
      ))}
    </div>
  );
}

function Candidates({
  pair,
  runDate,
  horizonDays,
  decimals,
  disclaimer,
}: {
  pair: PairId;
  runDate: string;
  horizonDays: number;
  decimals: number;
  disclaimer: string;
}) {
  const [date, setDate] = useState(runDate);
  const run = useApi(`run:${pair}:${date}`, () => api.forecastRun(pair, date));
  const rows: ForecastRow[] = (run.data?.rows ?? [])
    .filter((r) => r.horizon_days === horizonDays)
    .sort((a, b) => MODEL_ORDER.indexOf(a.model) - MODEL_ORDER.indexOf(b.model));
  const dates = run.data?.available_run_dates ?? [runDate];

  return (
    <section className="card" aria-labelledby="cand-title">
      <div className="card-head">
        <h2 id="cand-title" className="card-title">
          {t("drivers.candidates")}
        </h2>
        <label className="select-label">
          {t("drivers.runDate")}
          <select value={date} onChange={(e) => setDate(e.target.value)}>
            {dates.map((d) => (
              <option key={d} value={d}>
                {fmtDate(d)}
              </option>
            ))}
          </select>
        </label>
      </div>
      {run.error ? (
        <ErrorState error={run.error} onRetry={run.reload} />
      ) : run.loading && !run.data ? (
        <Loading height={120} />
      ) : rows.length === 0 ? (
        <EmptyState title={t("drivers.noRows")} />
      ) : (
        <div className={run.refreshing ? "table-scroll is-refreshing" : "table-scroll"}>
          <table className="table">
            <thead>
              <tr>
                <th scope="col">{t("ranges.model")}</th>
                <th scope="col" className="num-col">{t("ranges.range", { level: 80 })}</th>
                <th scope="col" className="num-col">{t("ranges.range", { level: 50 })}</th>
                <th scope="col" className="num-col">{t("drivers.center")}</th>
                <th scope="col">{t("drivers.status")}</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.model} className={r.served ? "row-served" : undefined}>
                  <th scope="row">
                    {MODEL_LABELS[r.model] ?? r.model}
                    <span className="cell-sub">{r.model_version}</span>
                  </th>
                  <td className="num num-col">{fmtRange(r.q10, r.q90, decimals)}</td>
                  <td className="num num-col">{fmtRange(r.q25, r.q75, decimals)}</td>
                  <td className="num num-col muted">{fmtRate(r.center, decimals)}</td>
                  <td>{r.served ? <span className="tag tag-info">{t("drivers.servedTag")}</span> : <span className="muted">{t("drivers.candidate")}</span>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <Disclaimer text={disclaimer} />
    </section>
  );
}
