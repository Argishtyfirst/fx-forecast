import { useState } from "react";
import type { AiView, ConversionSignal, HorizonForecast, SignalAction } from "../api/types";
import { MODEL_LABELS } from "../lib/constants";
import { fmtDateTime, fmtInt, fmtNum, fmtPct, fmtRate, fmtShortDate, fmtSigned } from "../lib/format";
import { Disclaimer } from "./Disclaimer";

/** Verdicts in plain words. The AI's no-lean reads "No clear lean"; the models' reads "No proven edge". */
export const VERDICT: Record<SignalAction, string> = {
  sell_now: "Yes, sell now",
  wait: "Wait",
  no_edge: "No clear edge",
};
const AI_VERDICT: Record<SignalAction, string> = { ...VERDICT, no_edge: "No clear lean" };
const STAT_VERDICT: Record<SignalAction, string> = { ...VERDICT, no_edge: "No proven edge" };
export const CONFIDENCE_LEVELS = ["none", "low", "medium", "high"] as const;
const AI_CONFIDENCE_LEVELS = ["low", "medium", "high"] as const;

const CURRENCY_SYMBOL: Record<string, string> = { EUR: "€", USD: "$" };
const per = (s: ConversionSignal) => `${s.receive} per ${CURRENCY_SYMBOL[s.sell] ?? s.sell}`;
const pct0 = (p: number) => `${Math.round(p * 100)}%`;

interface SignalPanelProps {
  horizons: HorizonForecast[];
  decimals: number;
  disclaimer: string;
}

type WithSignal = HorizonForecast & { signal: ConversionSignal };

/**
 * "Sell EUR now?" per horizon. The headline is the AI view's own call (experimental, labelled
 * with its live track record); the statistical models follow in one line with the risk of
 * waiting and the interest difference. Without an AI view, the statistical answer leads with
 * the risk and interest, never with a bare 50%. Below 900px one horizon shows at a time.
 */
export function SignalPanel({ horizons, decimals, disclaimer }: SignalPanelProps) {
  const rows = [...horizons]
    .sort((a, b) => a.days - b.days)
    .filter((h): h is WithSignal => Boolean(h.signal));
  const [picked, setPicked] = useState<string | null>(null);
  if (rows.length === 0) return null;
  const active =
    rows.find((r) => r.label === picked)?.label ?? (rows.find((r) => r.label === "1M") ?? rows[rows.length - 1]).label;
  const { sell, receive } = rows[0].signal;

  return (
    <section className="card signal-card" aria-labelledby="signal-title" data-testid="signal-panel">
      <div className="signal-head">
        <h2 id="signal-title" className="signal-title">
          Sell {sell} now?
        </h2>
        <div className="segmented signal-tabs" role="group" aria-label="Signal horizon">
          {rows.map((h) => (
            <button
              key={h.days}
              type="button"
              className={h.label === active ? "seg seg-active" : "seg"}
              aria-pressed={h.label === active}
              onClick={() => setPicked(h.label)}
            >
              {h.label}
            </button>
          ))}
        </div>
        <p className="signal-sub">
          For converting {sell} into {receive}.
          <span className="signal-sub-rule">
            {" "}
            The headline is an experimental AI read; the statistical models underneath have to beat a random walk in
            backtests before they lean.
          </span>
        </p>
      </div>

      <ol className="signal-grid">
        {rows.map((h) => (
          <li
            key={h.days}
            className={h.label === active ? "signal is-active" : "signal"}
            data-testid={`signal-${h.label}`}
            data-action={h.signal.action}
            data-source={h.signal.verdict_source}
            data-lead={h.ai_view ? "ai" : "statistical"}
          >
            <p className="signal-horizon">
              <span className="signal-label">{h.label}</span>
              <span>
                to <time dateTime={h.target_date}>{fmtShortDate(h.target_date)}</time>
              </span>
            </p>
            {h.ai_view ? (
              <AiHeadline ai={h.ai_view} label={h.label} />
            ) : (
              <StatisticalLead s={h.signal} label={h.label} />
            )}
            {h.ai_view ? (
              <StatisticalLine s={h.signal} label={h.label} decimals={decimals} />
            ) : (
              <StatisticalFacts s={h.signal} label={h.label} decimals={decimals} />
            )}
            {!h.ai_view && (
              <p className="ai-off" data-testid="ai-view-off">
                AI view: no forecast yet
              </p>
            )}
            <Evidence s={h.signal} ai={h.ai_view ?? null} decimals={decimals} />
          </li>
        ))}
      </ol>
      <Disclaimer text={disclaimer} />
    </section>
  );
}

function trackTag(ai: AiView): string {
  const t = ai.track_record;
  if (t.promoted) return `AI view · proven on ${fmtInt(t.n_scored)} live forecasts`;
  return `AI view · experimental · unproven (${fmtInt(Math.min(t.n_scored, t.required))} of ${fmtInt(t.required)} forecasts scored)`;
}

function trackRecordText(ai: AiView): string {
  const t = ai.track_record;
  const parts = [
    t.n_scored < t.required
      ? `Live track record: ${fmtInt(t.n_scored)} of ${fmtInt(t.required)} forecasts scored`
      : `Live track record: ${fmtInt(t.n_scored)} forecasts scored`,
  ];
  if (t.n_scored > 0 && t.hit_rate !== null) parts.push(`hit rate ${fmtPct(t.hit_rate, 1)}`);
  if (t.n_scored > 0 && t.brier !== null) parts.push(`Brier ${fmtNum(t.brier, 3)} (0.25 is a coin flip)`);
  const head = parts.join(", ");
  if (t.promoted) return `${head}. Promoted: meets the same rule as the statistical models; it decides the verdict.`;
  if (t.n_scored >= t.required) return `${head}. Does not meet the promotion rule, so it does not decide the verdict.`;
  return `${head}. Unproven, does not decide the verdict.`;
}

/** The headline: the AI's own call, its chance, confidence and reasoning, with an honest tag. */
function AiHeadline({ ai, label }: { ai: AiView; label: string }) {
  const meta = `${ai.model} · ${ai.provider} · prompt ${ai.prompt_version} · ${fmtDateTime(ai.generated_at)}`;
  return (
    <div className="ai-headline" data-testid="ai-view" data-promoted={ai.track_record.promoted}>
      <p className="signal-verdict" data-testid="signal-verdict">
        {AI_VERDICT[ai.lean]}
      </p>
      <p className="signal-prob" data-testid="signal-prob">
        <span className="num">{pct0(ai.prob_better_if_wait)}</span> chance of a better rate if you wait {label}
      </p>
      <ChanceTrack p={ai.prob_better_if_wait} />
      <div className="signal-confidence">
        <span className="signal-confidence-label" id={`conf-${label}`}>
          Confidence
        </span>
        <ConfidenceScale levels={AI_CONFIDENCE_LEVELS} level={ai.confidence} labelledBy={`conf-${label}`} />
      </div>
      <p className="ai-reasoning" data-testid="ai-reasoning">
        {ai.reasoning}
      </p>
      <p className="ai-tag" data-testid="ai-tag" title={meta}>
        {trackTag(ai)}
      </p>
    </div>
  );
}

/** Fallback lead without an AI view: the verdict in words, then what waiting costs. */
function StatisticalLead({ s, label }: { s: ConversionSignal; label: string }) {
  return (
    <>
      <p className="signal-verdict" data-testid="signal-verdict">
        {STAT_VERDICT[s.action]}
      </p>
      {s.action === "no_edge" ? (
        <p className="signal-lead" data-testid="signal-lead">
          Waiting {label} doesn&rsquo;t improve your expected rate
        </p>
      ) : (
        <>
          <p className="signal-prob" data-testid="signal-prob">
            <span className="num">{pct0(s.prob_better_if_wait)}</span> chance of a better rate if you wait {label}
          </p>
          <ChanceTrack p={s.prob_better_if_wait} />
        </>
      )}
    </>
  );
}

function RiskText({ s, decimals, prefix }: { s: ConversionSignal; decimals: number; prefix: string }) {
  return (
    <span data-testid="signal-risk">
      {prefix}
      <span className="num signal-risk-value">&plusmn;{fmtNum(s.risk_half_width_pct, 1)}%</span>{" "}
      <span className="keep">
        (<span className="num">
          {fmtRate(s.downside_p10_rate, decimals)} &ndash; {fmtRate(s.upside_p90_rate, decimals)}
        </span>{" "}
        {per(s)})
      </span>
    </span>
  );
}

function interestText(s: ConversionSignal): string | null {
  const year = s.carry_pct_per_year;
  if (year === null) return null;
  if (Math.abs(year) < 0.005) return `${s.receive} and ${s.sell} pay about the same`;
  const [more, less] = year > 0 ? [s.receive, s.sell] : [s.sell, s.receive];
  return `${more} pays ~${fmtNum(Math.abs(year), 2)}%/yr more than ${less}`;
}

/** Secondary, one compact line: the statistical models' answer, the risk of waiting and the interest. */
function StatisticalLine({ s, label, decimals }: { s: ConversionSignal; label: string; decimals: number }) {
  const interest = interestText(s);
  const head =
    s.verdict_source === "ai"
      ? "Verdict decided by the promoted AI view"
      : s.action === "no_edge"
        ? "Statistical models: no proven edge"
        : `Statistical models: ${VERDICT[s.action].toLowerCase()}, ${pct0(s.prob_better_if_wait)} chance of a better rate if you wait ${label} (confidence ${s.confidence})`;
  return (
    <p className="signal-stat" data-testid="signal-stat">
      <span className="signal-stat-head">{head}</span>
      <span className="sep" aria-hidden="true">
        {" "}
        &middot;{" "}
      </span>
      <RiskText s={s} decimals={decimals} prefix="risk of waiting " />
      {interest && (
        <>
          <span className="sep" aria-hidden="true">
            {" "}
            &middot;{" "}
          </span>
          <span data-testid="signal-interest" title="At policy rates; your bank's rates differ">
            {interest}
          </span>
        </>
      )}
    </p>
  );
}

/** Fallback facts without an AI view: risk and interest as the lead's supporting lines. */
function StatisticalFacts({ s, label, decimals }: { s: ConversionSignal; label: string; decimals: number }) {
  const interest = interestText(s);
  return (
    <dl className="signal-facts">
      <div>
        <dt>Risk of waiting</dt>
        <dd>
          <RiskText s={s} decimals={decimals} prefix="" />
        </dd>
      </div>
      {interest && (
        <div>
          <dt>Interest</dt>
          <dd>
            <span data-testid="signal-interest">
              Holding {interest}
              {s.carry_amount !== null && (
                <>
                  {" "}
                  <span className="keep">
                    (~<span className="num">{fmtRate(Math.abs(s.carry_amount), decimals)}</span> {per(s)} over {label})
                  </span>
                </>
              )}
            </span>
            <span className="signal-note">at policy rates; your bank&rsquo;s rates differ</span>
          </dd>
        </div>
      )}
    </dl>
  );
}

function Evidence({ s, ai, decimals }: { s: ConversionSignal; ai: AiView | null; decimals: number }) {
  return (
    <details className="signal-evidence">
      <summary>Evidence</summary>
      <dl>
        {ai && (
          <>
            <div className="evidence-summary">
              <dt>AI view</dt>
              <dd data-testid="ai-track">{trackRecordText(ai)}</dd>
            </div>
            <div>
              <dt>AI model</dt>
              <dd>
                {ai.model} &middot; {ai.provider}
              </dd>
            </div>
            <div>
              <dt>Generated</dt>
              <dd>
                <time dateTime={ai.generated_at}>{fmtDateTime(ai.generated_at)}</time>
              </dd>
            </div>
          </>
        )}
        <div className="evidence-summary">
          <dt>Statistical models</dt>
          <dd>{s.summary}</dd>
        </div>
        <div>
          <dt>Model behind the verdict</dt>
          <dd>{MODEL_LABELS[s.model] ?? s.model}</dd>
        </div>
        <div>
          <dt>Beats random walk</dt>
          <dd>{s.model_beats_random_walk ? "Yes" : "No"}</dd>
        </div>
        <div>
          <dt>Direction hit rate</dt>
          <dd className="num">{s.hit_rate === null ? "—" : fmtPct(s.hit_rate, 1)}</dd>
        </div>
        <div>
          <dt>Diebold-Mariano p</dt>
          <dd className="num">{s.dm_pvalue === null ? "—" : fmtNum(s.dm_pvalue, 2)}</dd>
        </div>
        <div>
          <dt>Backtest forecasts</dt>
          <dd className="num">{fmtInt(s.n_obs)}</dd>
        </div>
        <div>
          <dt>1 in 10 chance of</dt>
          <dd className="num" data-testid="signal-downside">
            &le; {fmtRate(s.downside_p10_rate, decimals)}
          </dd>
        </div>
        <div>
          <dt>1 in 10 chance of</dt>
          <dd className="num" data-testid="signal-upside">
            &ge; {fmtRate(s.upside_p90_rate, decimals)}
          </dd>
        </div>
        <div>
          <dt>Center vs spot</dt>
          <dd className="num">{`${fmtSigned(s.expected_change_pct, 2)}%`}</dd>
        </div>
      </dl>
    </details>
  );
}

/** Where P(better rate) sits between "worse" and "better", with the coin-flip midpoint marked. */
function ChanceTrack({ p }: { p: number }) {
  const pos = Math.max(0, Math.min(1, p)) * 100;
  return (
    <div className="chance" aria-hidden="true">
      <div className="chance-track">
        <span className="chance-mid" />
        <span className="chance-dot" style={{ left: `${pos}%` }} />
      </div>
      <div className="chance-ends">
        <span>worse</span>
        <span>even</span>
        <span>better</span>
      </div>
    </div>
  );
}

function ConfidenceScale({
  levels,
  level,
  labelledBy,
}: {
  levels: readonly string[];
  level: string;
  labelledBy: string;
}) {
  const index = levels.indexOf(level);
  return (
    <ol className="conf-scale" aria-labelledby={labelledBy} data-testid="confidence-scale" data-level={level}>
      {levels.map((l, i) => (
        <li
          key={l}
          className={i === index ? "conf-step conf-current" : i < index ? "conf-step conf-below" : "conf-step"}
          aria-current={i === index ? "true" : undefined}
        >
          {l}
        </li>
      ))}
    </ol>
  );
}
