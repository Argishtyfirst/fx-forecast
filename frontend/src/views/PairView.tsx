import { api } from "../api/client";
import type { PairId } from "../api/types";
import { DataStatus } from "../components/DataStatus";
import { Disclaimer } from "../components/Disclaimer";
import { FanChart } from "../components/FanChart";
import { HorizonCard } from "../components/HorizonCard";
import { SignalPanel } from "../components/SignalPanel";
import { EmptyState, ErrorState, Loading } from "../components/States";
import { PAIR_SOURCES, PAIRS } from "../lib/constants";
import { historyWindow } from "../lib/fan";
import { addDays, fmtDate, fmtRate, isoDate } from "../lib/format";
import { useApi } from "../lib/useApi";

export function PairView({ pair }: { pair: PairId }) {
  const meta = PAIRS[pair];
  const latest = useApi(`latest:${pair}`, () => api.latestForecast(pair));
  const forecast = latest.data ?? null;
  // Rates load once the spot date is known, so the window ends exactly at the spot.
  const anchor = latest.loading ? null : (forecast?.spot_date ?? isoDate(new Date()));
  const rates = useApi(anchor ? `rates:${pair}:${anchor}` : null, () =>
    api.rates(pair, addDays(anchor as string, -200), anchor as string),
  );
  const history = rates.data ? historyWindow(rates.data.rates, anchor as string, 90) : [];

  const horizons = forecast ? [...forecast.horizons].sort((a, b) => a.days - b.days) : [];
  const domain: [number, number] = horizons.length
    ? [
        Math.min(...horizons.map((h) => h.bands["95"]?.[0] ?? h.center)),
        Math.max(...horizons.map((h) => h.bands["95"]?.[1] ?? h.center)),
      ]
    : [0, 1];

  return (
    <div className="view">
      <DataStatus relevant={PAIR_SOURCES[pair]} extraStale={forecast?.stale_sources} />

      <section className="view-head pair-head">
        <div>
          <h1 className="view-title">{meta.label}</h1>
          <p className="view-sub">
            {meta.sourceLabel}
            {forecast && (
              <>
                {" "}
                &middot; forecast run <time dateTime={forecast.as_of}>{fmtDate(forecast.as_of)}</time>
              </>
            )}
          </p>
        </div>
        {(forecast || history.length > 0) && (
          <div className="spot">
            <span className="spot-label">
              {forecast ? "Spot" : "Last rate"} &middot;{" "}
              {fmtDate(forecast?.spot_date ?? history[history.length - 1].date)}
            </span>
            <span className="spot-value" data-testid="spot">
              {fmtRate(forecast?.spot ?? history[history.length - 1].rate, meta.decimals)}
            </span>
          </div>
        )}
      </section>

      {forecast && horizons.length > 0 && (
        <SignalPanel horizons={horizons} decimals={meta.decimals} disclaimer={forecast.disclaimer} />
      )}

      <section className="card chart-card" aria-labelledby="fan-title">
        <div className="card-head">
          <h2 id="fan-title" className="card-title">
            Probability bands
          </h2>
          <FanLegend />
        </div>
        {latest.error ? (
          <ErrorState title="Could not load the forecast" error={latest.error} onRetry={latest.reload} />
        ) : rates.error ? (
          <ErrorState title="Could not load the rate history" error={rates.error} onRetry={rates.reload} />
        ) : latest.loading || rates.loading ? (
          <Loading label="Loading the fan chart" height={330} />
        ) : (
          <>
            <FanChart pairLabel={meta.label} decimals={meta.decimals} history={history} forecast={forecast} />
            {forecast ? (
              <>
                <p className="chart-note">
                  Each band starts at zero width on the spot date and widens to the 1D, 1W and 1M horizons,
                  interpolated linearly in trading-day time. The forecast section is drawn at a wider time scale than
                  the history. Ticks mark central bank meetings inside the horizons.
                </p>
                <Disclaimer text={forecast.disclaimer} />
              </>
            ) : (
              <EmptyState title="No forecast yet">
                The daily pipeline writes the first forecast after the 17:00 CET ingest. The rate history is shown
                above.
              </EmptyState>
            )}
          </>
        )}
      </section>

      {forecast && horizons.length > 0 && (
        <section className="hcards" aria-label="Forecast by horizon">
          {horizons.map((h) => (
            <HorizonCard
              key={h.days}
              horizon={h}
              decimals={meta.decimals}
              spot={forecast.spot}
              domain={domain}
              disclaimer={forecast.disclaimer}
            />
          ))}
        </section>
      )}
    </div>
  );
}

function FanLegend() {
  return (
    <ul className="legend" aria-label="Legend">
      <li>
        <span className="legend-swatch fan-band-95" />
        95%
      </li>
      <li>
        <span className="legend-swatch fan-band-80" />
        80%
      </li>
      <li>
        <span className="legend-swatch fan-band-50" />
        50%
      </li>
      <li>
        <span className="legend-line legend-history" />
        History
      </li>
      <li>
        <span className="legend-line legend-center" />
        Center
      </li>
    </ul>
  );
}
