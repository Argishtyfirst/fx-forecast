import { useCallback, useRef, useState } from "react";
import { api } from "../api/client";
import type { HorizonForecast, PairId, QuotesResponse } from "../api/types";
import { ConvertCalculator } from "../components/ConvertCalculator";
import { ProviderQuotes, rankQuotes } from "../components/ProviderQuotes";
import { DataStatus } from "../components/DataStatus";
import { DecisionHero, NEED } from "../components/DecisionHero";
import { Disclaimer } from "../components/Disclaimer";
import { FanChart } from "../components/FanChart";
import { EmptyState, ErrorState, Loading } from "../components/States";
import { BANK_LABELS, MODEL_LABELS, PAIR_SOURCES, PAIRS } from "../lib/constants";
import { historyWindow } from "../lib/fan";
import { addDays, fmtDate, fmtRange, fmtRate, fmtShortDate, isoDate } from "../lib/format";
import { useApi } from "../lib/useApi";
import { t } from "../i18n";
import { useAmount, useDebounced, useQuoteGroup } from "../lib/useAmount";

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

  // The amount to convert, shared by the calculator and the provider rates (AMD pairs only).
  const [amount, setAmount] = useAmount(meta.base);
  const debounced = useDebounced(amount, 400);
  const hasQuotes = meta.quote === "AMD";
  const quotes = useApi(hasQuotes ? `quotes:${pair}:${debounced}` : null, () => api.quotes(pair, debounced));
  // Keep the last rates on screen while a new amount loads, so the card does not flash.
  const lastQuotes = useRef<{ pair: string; data: QuotesResponse | null } | null>(null);
  if (quotes.data !== undefined) lastQuotes.current = { pair, data: quotes.data };
  const quotesData = quotes.data ?? (lastQuotes.current?.pair === pair ? lastQuotes.current.data : undefined);
  const [group, setGroup] = useQuoteGroup();
  // The best fresh quote in the chosen group; if every one is stale, the row is hidden.
  const best =
    quotesData && quotesData.amount === amount ? (rankQuotes(quotesData.quotes, group).find((q) => !q.stale) ?? null) : null;
  const selectedHorizon = horizons.find((h) => h.label === selected) ?? horizons[horizons.length - 1];

  return (
    <div className="view">
      <DataStatus relevant={PAIR_SOURCES[pair]} extraStale={forecast?.stale_sources} />

      {latest.error ? (
        <ErrorState title={t("pair.errForecast")} error={latest.error} onRetry={latest.reload} />
      ) : latest.loading ? (
        <Loading label={t("pair.loadingForecast")} height={420} />
      ) : (
        <div className="decision-grid">
          {forecast ? (
            <div className="decision-col">
              <DecisionHero pair={meta} forecast={forecast} selected={selected} onSelect={setSelected} />
              {selectedHorizon && (
                <ConvertCalculator
                  pair={meta}
                  horizon={selectedHorizon}
                  spot={forecast.spot}
                  amount={amount}
                  onAmount={setAmount}
                  best={best}
                />
              )}
              {/* A 404 (null) means no provider rates for this pair: the card stays hidden. */}
              {hasQuotes && quotesData !== null && (quotesData !== undefined || quotes.loading || quotes.error) && (
                <ProviderQuotes
                  data={quotesData ?? undefined}
                  loading={quotes.loading}
                  error={quotes.error}
                  amount={debounced}
                  base={meta.base}
                  group={group}
                  onGroup={setGroup}
                />
              )}
            </div>
          ) : (
            <section className="card hero" data-testid="decision-hero" data-lean="none">
              <h1 className="hero-question">
                {t("hero.question", { base: meta.base, quote: meta.quote })}
              </h1>
              <EmptyState title={t("pair.noForecast")}>{t("pair.noForecastBody")}</EmptyState>
            </section>
          )}

          <section className="card chart-card" aria-labelledby="fan-title">
            <div className="card-head">
              <h2 id="fan-title" className="card-title">
                {meta.label}
                {(forecast || lastRate) && (
                  <span className="card-title-sub">
                    {t("pair.spotOn", {
                      rate: fmtRate(forecast?.spot ?? lastRate?.rate, meta.decimals),
                      date: fmtShortDate(forecast?.spot_date ?? lastRate?.date ?? ""),
                    })}
                  </span>
                )}
              </h2>
              <FanLegend ai={horizons.some((h) => h.ai_view)} />
            </div>
            {rates.error ? (
              <ErrorState title={t("pair.errHistory")} error={rates.error} onRetry={rates.reload} />
            ) : rates.loading ? (
              <Loading label={t("pair.loadingChart")} height={300} />
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
                  {t("pair.chartNote", { source: meta.sourceLabel })}
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
        {t("ranges.title")}
      </h2>
      <div className="table-scroll">
        <table className="table ranges-table">
          <thead>
            <tr>
              <th scope="col">{t("ranges.horizon")}</th>
              <th scope="col">{t("ranges.target")}</th>
              <th scope="col" className="num-col">
                {t("ranges.range", { level: 80 })}
              </th>
              <th scope="col" className="num-col">
                {t("ranges.range", { level: 50 })}
              </th>
              <th scope="col" className="num-col">
                {t("ranges.range", { level: 95 })}
              </th>
              <th scope="col">{t("ranges.model")}</th>
              <th scope="col">{t("ranges.meetings")}</th>
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
                  {h.bands["80"] ? fmtRange(h.bands["80"][0], h.bands["80"][1], decimals) : t("fmt.na")}
                </td>
                <td className="num num-col">
                  {h.bands["50"] ? fmtRange(h.bands["50"][0], h.bands["50"][1], decimals) : t("fmt.na")}
                </td>
                <td className="num num-col">
                  {h.bands["95"] ? fmtRange(h.bands["95"][0], h.bands["95"][1], decimals) : t("fmt.na")}
                </td>
                <td>{MODEL_LABELS[h.model] ?? h.model}</td>
                <td data-testid="range-meetings">
                  {h.meetings.length
                    ? h.meetings.map((m) => `${BANK_LABELS[m.bank] ?? m.bank} ${fmtShortDate(m.date)}`).join(", ")
                    : t("ranges.none")}
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
    <ul className="legend" aria-label={t("legend.aria")}>
      <li>
        <span className="legend-swatch legend-fan" />
        {t("legend.statRange")}
      </li>
      {ai && (
        <li>
          <span className="legend-line legend-ai" />
          {t("legend.aiPath")}
        </li>
      )}
      <li>
        <span className="legend-line legend-history" />
        {t("legend.history")}
      </li>
    </ul>
  );
}
