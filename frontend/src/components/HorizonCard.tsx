import type { HorizonForecast } from "../api/types";
import { BANK_LABELS, HORIZONS, MODEL_LABELS } from "../lib/constants";
import { fmtRange, fmtRate, fmtShortDate, fmtWeekdayDate } from "../lib/format";
import { Disclaimer } from "./Disclaimer";
import { RangeBar } from "./RangeBar";

interface HorizonCardProps {
  horizon: HorizonForecast;
  decimals: number;
  spot: number;
  /** Shared value domain, so the three range bars are comparable. */
  domain: [number, number];
  disclaimer: string;
}

export function HorizonCard({ horizon: h, decimals, spot, domain, disclaimer }: HorizonCardProps) {
  const b80 = h.bands["80"];
  const b50 = h.bands["50"];
  const b95 = h.bands["95"];
  const long = HORIZONS.find((x) => x.days === h.days)?.long ?? `${h.days} trading days`;
  return (
    <article className="hcard" data-testid={`horizon-card-${h.label}`}>
      <header className="hcard-head">
        <span className="hcard-label">{h.label}</span>
        <span className="hcard-long">{long}</span>
      </header>
      <p className="hcard-target">
        Target <time dateTime={h.target_date}>{fmtWeekdayDate(h.target_date)}</time>
      </p>

      <p className="hcard-kicker">80% range</p>
      <p className="hcard-range num" data-testid="range-80">
        {b80 ? fmtRange(b80[0], b80[1], decimals) : "—"}
      </p>
      <RangeBar horizon={h} spot={spot} domain={domain} />

      <dl className="hcard-grid">
        <div>
          <dt>Center</dt>
          <dd className="num">{fmtRate(h.center, decimals)}</dd>
        </div>
        <div>
          <dt>50%</dt>
          <dd className="num">{b50 ? fmtRange(b50[0], b50[1], decimals) : "—"}</dd>
        </div>
        <div>
          <dt>95%</dt>
          <dd className="num">{b95 ? fmtRange(b95[0], b95[1], decimals) : "—"}</dd>
        </div>
        <div>
          <dt>Model</dt>
          <dd>
            {MODEL_LABELS[h.model] ?? h.model}
            <span className="hcard-version">{h.model_version}</span>
          </dd>
        </div>
      </dl>

      <div className="hcard-meetings">
        <span className="hcard-meetings-label">Meetings inside</span>
        {h.meetings.length ? (
          <ul>
            {h.meetings.map((m) => (
              <li key={`${m.bank}-${m.date}`} data-testid="card-meeting">
                <span className="bank-tag">{BANK_LABELS[m.bank] ?? m.bank}</span>
                <time dateTime={m.date}>{fmtShortDate(m.date)}</time>
              </li>
            ))}
          </ul>
        ) : (
          <span className="hcard-none">None, bands not widened</span>
        )}
      </div>
      <Disclaimer text={disclaimer} />
    </article>
  );
}
