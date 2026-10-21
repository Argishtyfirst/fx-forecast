import { useState } from "react";
import type { AiView, ConversionSignal, HorizonForecast, SignalAction, SignalConfidence } from "../api/types";
import { MODEL_LABELS } from "../lib/constants";
import { fmtDateTime, fmtInt, fmtNum, fmtPct, fmtRate, fmtShortDate, fmtSigned } from "../lib/format";
import { useMediaQuery } from "../lib/useMediaQuery";
import { Disclaimer } from "./Disclaimer";

/** FR-17 verdicts in plain words. "No clear edge" is a full answer, not a missing one. */
export const VERDICT: Record<SignalAction, string> = {
  sell_now: "Yes, sell now",
  wait: "Wait",
  no_edge: "No clear edge",
};
export const CONFIDENCE_LEVELS: SignalConfidence[] = ["none", "low", "medium", "high"];

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
 * "Sell EUR now?": one answer per horizon. With no proven edge the panel leads with what waiting
 * costs (risk, interest difference); a lean leads with its probability. Below 900px one horizon
 * shows at a time, so the fan chart stays near the top.
 */
export function SignalPanel({ horizons, decimals, disclaimer }: SignalPanelProps) {
  const rows = [...horizons]
    .sort((a, b) => a.days - b.days)
    .filter((h): h is WithSignal => Boolean(h.signal));
  const [picked, setPicked] = useState<string | null>(null);
  const compact = useMediaQuery("(max-width: 900px)");
  if (rows.length === 0) return null;
  const active = rows.find((r) => r.label === picked)?.label ?? (rows.find((r) => r.label === "1M") ?? rows[rows.length - 1]).label;
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
            The verdict leans only when a model has beaten the random walk in backtests and called the direction right
            more than half the time.
          </span>
        </p>
      </div>

      <ol className="signal-grid">
        {rows.map((h) => (
          <SignalRow
            key={h.days}
            h={h}
            signal={h.signal}
            decimals={decimals}
            active={h.label === active}
            compact={compact}
          />
        ))}
      </ol>
      <Disclaimer text={disclaimer} />
    </section>
  );
}

function SignalRow({
  h,
  signal: s,
  decimals,
  active,
  compact,
}: {
  h: WithSignal;
  signal: ConversionSignal;
  decimals: number;
  active: boolean;
  compact: boolean;
}) {
  const noEdge = s.action === "no_edge";
  const fromAi = s.verdict_source === "ai";
  return (
    <li
      className={active ? "signal is-active" : "signal"}
      data-testid={`signal-${h.label}`}
      data-action={s.action}
      data-source={s.verdict_source}
    >
      <div className="signal-top">
        <p className="signal-horizon">
          <span className="signal-label">{h.label}</span>
          <span>
            to <time dateTime={h.target_date}>{fmtShortDate(h.target_date)}</time>
          </span>
        </p>
        {noEdge && (
          <p className="signal-verdict-tag" data-testid="signal-verdict">
            {VERDICT[s.action]}
          </p>
        )}
      </div>

      {noEdge ? (
        <p className="signal-lead" data-testid="signal-lead">
          Waiting {h.label} doesn&rsquo;t improve your expected rate
        </p>
      ) : (
        <>
          <p className="signal-verdict" data-testid="signal-verdict">
            {VERDICT[s.action]}
          </p>
          <p className="signal-prob" data-testid="signal-prob">
            <span className="num">{pct0(s.prob_better_if_wait)}</span> chance of a better rate if you wait {h.label}
          </p>
          <ChanceTrack p={s.prob_better_if_wait} />
        </>
      )}
      {fromAi && (
        <p className="signal-source" data-testid="verdict-source">
          Verdict from the AI view, promoted on its live track record
        </p>
      )}

      <dl className="signal-facts">
        <div data-testid="signal-risk">
          <dt>Risk of waiting</dt>
          <dd>
            <span className="num signal-risk-value">&plusmn;{fmtNum(s.risk_half_width_pct, 1)}%</span>{" "}
            <span className="signal-range">
              (80% range{" "}
              <span className="num">
                {fmtRate(s.downside_p10_rate, decimals)} &ndash; {fmtRate(s.upside_p90_rate, decimals)}
              </span>{" "}
              {per(s)})
            </span>
          </dd>
        </div>
        {s.carry_pct_per_year !== null && (
          <div data-testid="signal-interest">
            <dt>Interest</dt>
            <dd>
              <InterestLine s={s} label={h.label} decimals={decimals} />
              <span className="signal-note">at policy rates; your bank&rsquo;s rates differ</span>
            </dd>
          </div>
        )}
      </dl>

      <div className={noEdge ? "signal-secondary" : "signal-secondary signal-secondary-lean"}>
        {noEdge && (
          <p className="signal-prob signal-prob-secondary" data-testid="signal-prob">
            <span className="num">{pct0(s.prob_better_if_wait)}</span> chance of a better rate if you wait {h.label}
          </p>
        )}
        <div className="signal-confidence">
          <span className="signal-confidence-label" id={`conf-${h.label}`}>
            Confidence
          </span>
          <ConfidenceScale level={s.confidence} labelledBy={`conf-${h.label}`} />
        </div>
      </div>

      {!noEdge && <p className="signal-summary">{s.summary}</p>}

      <details className="signal-evidence">
        <summary>Evidence behind the verdict</summary>
        <dl>
          {noEdge && (
            <div className="evidence-summary">
              <dt>In one sentence</dt>
              <dd>{s.summary}</dd>
            </div>
          )}
          <div className="evidence-summary">
            <dt>When it leans</dt>
            <dd>
              Only when a model met the promotion rule (MAE ratio below 0.98, Diebold-Mariano p below 0.10 over 250
              days) and called the direction right more than half the time.
            </dd>
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
            <dt>MAE ratio vs random walk</dt>
            <dd className="num">{s.mae_ratio_rw === null ? "—" : fmtNum(s.mae_ratio_rw, 3)}</dd>
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

      <AiBlock ai={h.ai_view ?? null} label={h.label} compact={compact} />
    </li>
  );
}

function InterestLine({ s, label, decimals }: { s: ConversionSignal; label: string; decimals: number }) {
  const year = s.carry_pct_per_year as number;
  const amount = s.carry_amount;
  const amountText =
    amount === null ? null : (
      <>
        {" "}
        <span className="keep">
          (~<span className="num">{fmtRate(Math.abs(amount), decimals)}</span> {per(s)} over {label})
        </span>
      </>
    );
  if (Math.abs(year) < 0.005) {
    return (
      <span className="signal-interest-text">
        Holding {s.receive} or {s.sell} pays about the same
      </span>
    );
  }
  // Name the currency that pays more.
  const [more, less] = year > 0 ? [s.receive, s.sell] : [s.sell, s.receive];
  return (
    <span className="signal-interest-text">
      Holding {more} pays ~<span className="num">{fmtNum(Math.abs(year), 2)}%</span>/yr more than {less}
      {amountText}
    </span>
  );
}

function trackRecordText(ai: AiView): string {
  const t = ai.track_record;
  const parts: string[] = [];
  parts.push(
    t.n_scored < t.required
      ? `Live track record: ${fmtInt(t.n_scored)} of ${fmtInt(t.required)} forecasts scored`
      : `Live track record: ${fmtInt(t.n_scored)} forecasts scored`,
  );
  if (t.n_scored > 0) {
    if (t.hit_rate !== null) parts.push(`hit rate ${fmtPct(t.hit_rate, 1)}`);
    if (t.brier !== null) parts.push(`Brier ${fmtNum(t.brier, 3)} (0.25 is a coin flip)`);
  }
  const head = parts.join(", ");
  if (t.promoted) return `${head}. Promoted: meets the same rule as the statistical models; it decides the verdict.`;
  if (t.n_scored >= t.required) return `${head}. Does not meet the promotion rule, so it does not decide the verdict.`;
  return `${head}. Unproven, does not decide the verdict.`;
}

/**
 * Experimental AI view: under the statistical answer, never styled above it. On small screens
 * the reasoning and track record fold behind the summary line, which still says "unproven".
 */
function AiBlock({ ai, label, compact }: { ai: AiView | null; label: string; compact: boolean }) {
  if (!ai) {
    return (
      <div className="ai-view ai-view-off" data-testid="ai-view">
        <p className="ai-off">AI view off (no forecast yet)</p>
      </div>
    );
  }
  const t = ai.track_record;
  const status = t.promoted ? "promoted" : "unproven";
  return (
    // Uncontrolled: open by default on wide screens; remounts (resetting the default) only when
    // the layout switches, so the reader's own toggling is never fought.
    <details key={compact ? "compact" : "wide"} className="ai-view" data-testid="ai-view" data-promoted={t.promoted} open={!compact}>
      <summary className="ai-summary">
        <span className="ai-label">
          AI view <span aria-hidden="true">&middot;</span> <span className="ai-experimental">experimental</span>
        </span>
        <span className="ai-prob" data-testid="ai-prob">
          <span className="num">{pct0(ai.prob_better_if_wait)}</span> chance of a better rate if you wait {label}
          <span className="ai-sep" aria-hidden="true">
            {" "}
            &middot;{" "}
          </span>
          <span className="ai-confidence">confidence {ai.confidence}</span>
          <span className="ai-status">
            <span aria-hidden="true"> &middot; </span>
            {status}
          </span>
        </span>
      </summary>
      <p className="ai-reasoning">{ai.reasoning}</p>
      <p className="ai-meta">
        {ai.model} &middot; {ai.provider} &middot; <time dateTime={ai.generated_at}>{fmtDateTime(ai.generated_at)}</time>
      </p>
      <p className="ai-track" data-testid="ai-track">
        {trackRecordText(ai)}
      </p>
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

function ConfidenceScale({ level, labelledBy }: { level: SignalConfidence; labelledBy: string }) {
  const index = CONFIDENCE_LEVELS.indexOf(level);
  return (
    <ol className="conf-scale" aria-labelledby={labelledBy} data-testid="confidence-scale" data-level={level}>
      {CONFIDENCE_LEVELS.map((l, i) => (
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
