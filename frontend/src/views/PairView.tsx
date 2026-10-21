import { useCallback, useState } from "react";
import { api } from "../api/client";
import type { HorizonForecast, PairId } from "../api/types";
import { DataStatus } from "../components/DataStatus";
import { DecisionHero, NEED } from "../components/DecisionHero";
import { Disclaimer } from "../components/Disclaimer";
import { FanChart } from "../components/FanChart";
import { EmptyState, ErrorState, Loading } from "../components/States";
import { BANK_LABELS, MODEL_LABELS, PAIR_SOURCES, PAIRS } from "../lib/constants";
import { historyWindow } from "../lib/fan";
import { addDays, fmtDate, fmtRange, fmtRate, fmtShortDate, isoDate } from "../lib/format";
import { useApi } from "../lib/useApi";

const HORIZON_KEY = "fxf-horizon";
const HORIZON_LABELS = ["1D", "1W", "1M"];

function readHorizon(): string {
  try {
    const v = window.localStorage.getItem(HORIZON_KEY);
    return v && HORIZON_LABELS.includes(v) ? v : "1M";
  } catch {
    return "1M";
  }
}

/** The chosen horizon ("I need AMD within a month"), remembered across visits. */
export function useHorizonChoice(): [string, (label: string) => void] {
  const [label, setLabel] = useState(readHorizon);
  const choose = useCallback((next: string) => {
    setLabel(next);
    try {
      window.localStorage.setItem(HORIZON_KEY, next);
    } catch {
      // Storage blocked: the choice still holds for this session.
    }
  }, []);
  return [label, choose];
}

export function PairView({ pair }: { pair: PairId }) {
  const meta = PAIRS[pair];
  const [selected, setSelected] = useHorizonChoice();
  const latest = useApi(`latest:${pair}`, () => api.latestForecast(pair));
  const forecast = latest.data ?? null;
  // Rates load once the spot date is known, so the window ends exactly at the spot.
  const anchor = latest.loading ? null : (forecast?.spot_date ?? isoDate(new Date()));
  const rates = useApi(anchor ? `rates:${pair}:${anchor}` : null, () =>
    api.rates(pair, addDays(anchor as string, -200), anchor as string),
  );
  const history = rates.data ? historyWindow(rates.data.rates, anchor as string, 90) : [];
  const horizons = forecast ? [...forecast.horizons].sort((a, b) => a.days - b.days) : [];
  const lastRate = history[history.length - 1];

  return (
    <div className="view">
      <DataStatus relevant={PAIR_SOURCES[pair]} extraStale={forecast?.stale_sources} />

      {latest.error ? (
        <ErrorState title="Could not load the forecast" error={latest.error} onRetry={latest.reload} />
      ) : latest.loading ? (
        <Loading label="Loading the forecast" height={420} />
      ) : (
        <div className="decision-grid">
          {forecast ? (
            <DecisionHero pair={meta} forecast={forecast} selected={selected} onSelect={setSelected} />
          ) : (
            <section className="card hero" data-testid="decision-hero" data-lean="none">
              <h1 className="hero-question">
                Sell {meta.base} for {meta.quote} now?
              </h1>
              <EmptyState title="No forecast yet">
                The daily pipeline writes the first forecast after the 17:00 CET ingest.
              </EmptyState>
            </section>
          )}

          <section className="card chart-card" aria-labelledby="fan-title">
            <div className="card-head">
              <h2 id="fan-title" className="card-title">
                {meta.label}
                {(forecast || lastRate) && (
                  <span className="card-title-sub">
                    spot <span className="num">{fmtRate(forecast?.spot ?? lastRate?.rate, meta.decimals)}</span> on{" "}
                    {fmtShortDate(forecast?.spot_date ?? lastRate?.date ?? "")}
                  </span>
                )}
              </h2>
              <FanLegend ai={horizons.some((h) => h.ai_view)} />
            </div>
            {rates.error ? (
              <ErrorState title="Could not load the rate history" error={rates.error} onRetry={rates.reload} />
            ) : rates.loading ? (
              <Loading label="Loading the chart" height={300} />
            ) : (
              <>
                <FanChart
                  pairLabel={meta.label}
                  decimals={meta.decimals}
                  history={history}
                  forecast={forecast}
                  selected={forecast ? selected : undefined}
                />
                <p className="chart-note">
                  {meta.sourceLabel}, 90 trading days. The forecast side is drawn at a wider time scale; ticks mark
                  central bank meetings.
                </p>
                {forecast && <Disclaimer text={forecast.disclaimer} />}
              </>
            )}
          </section>
        </div>
      )}

      {forecast && horizons.length > 0 && (
        <RangesTable horizons={horizons} decimals={meta.decimals} selected={selected} disclaimer={forecast.disclaimer} />
      )}
    </div>
  );
}

/** The chart's table twin: statistical ranges per horizon, without repeating the hero. */
function RangesTable({
  horizons,
  decimals,
  selected,
  disclaimer,
}: {
  horizons: HorizonForecast[];
  decimals: number;
  selected: string;
  disclaimer: string;
}) {
  return (
    <section className="card" aria-labelledby="ranges-title" data-testid="ranges">
      <h2 id="ranges-title" className="card-title">
        Statistical ranges by horizon
      </h2>
      <div className="table-scroll">
        <table className="table ranges-table">
          <thead>
            <tr>
              <th scope="col">Horizon</th>
              <th scope="col">Target</th>
              <th scope="col" className="num-col">
                80% range
              </th>
              <th scope="col" className="num-col">
                50% range
              </th>
              <th scope="col" className="num-col">
                95% range
              </th>
              <th scope="col">Model</th>
              <th scope="col">Meetings inside</th>
            </tr>
          </thead>
          <tbody>
            {horizons.map((h) => (
              <tr
                key={h.days}
                className={h.label === selected ? "row-selected" : undefined}
                data-testid={`range-row-${h.label}`}
                aria-current={h.label === selected ? "true" : undefined}
              >
                <th scope="row">
                  {h.label}
                  <span className="cell-sub">{NEED[h.label]}</span>
                </th>
                <td>{fmtDate(h.target_date)}</td>
                <td className="num num-col" data-testid="range-80">
                  {h.bands["80"] ? fmtRange(h.bands["80"][0], h.bands["80"][1], decimals) : "n/a"}
                </td>
                <td className="num num-col">
                  {h.bands["50"] ? fmtRange(h.bands["50"][0], h.bands["50"][1], decimals) : "n/a"}
                </td>
                <td className="num num-col">
                  {h.bands["95"] ? fmtRange(h.bands["95"][0], h.bands["95"][1], decimals) : "n/a"}
                </td>
                <td>{MODEL_LABELS[h.model] ?? h.model}</td>
                <td data-testid="range-meetings">
                  {h.meetings.length
                    ? h.meetings.map((m) => `${BANK_LABELS[m.bank] ?? m.bank} ${fmtShortDate(m.date)}`).join(", ")
                    : "None"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <Disclaimer text={disclaimer} />
    </section>
  );
}

function FanLegend({ ai }: { ai: boolean }) {
  return (
    <ul className="legend" aria-label="Legend">
      <li>
        <span className="legend-swatch legend-fan" />
        Statistical range
      </li>
      {ai && (
        <li>
          <span className="legend-line legend-ai" />
          AI expected path
        </li>
      )}
      <li>
        <span className="legend-line legend-history" />
        History
      </li>
    </ul>
  );
}
