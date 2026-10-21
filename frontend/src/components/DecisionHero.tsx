import { useId, useState } from "react";
import type {
  AiView,
  ConversionSignal,
  HorizonForecast,
  LatestForecastResponse,
  MeetingRiskOut,
  SignalAction,
} from "../api/types";
import { BANK_LABELS, MODEL_LABELS, type PairMeta } from "../lib/constants";
import { fmtDateTime, fmtInt, fmtNum, fmtPct, fmtRate, fmtShortDate } from "../lib/format";
import { verdictText } from "../lib/verdict";
import { Disclaimer } from "./Disclaimer";
import { SellNowIcon, SwingIcon, UnclearIcon, WaitIcon } from "./Icons";

/** Plain-word verdicts. Wording carries the answer; the accent and the icon only reinforce it. */
export const VERDICT: Record<SignalAction, string> = {
  sell_now: "Sell now",
  wait: "Wait",
  no_edge: "No clear answer",
};

/** The horizon control, phrased as the user's need. */
export const NEED: Record<string, string> = { "1D": "tomorrow", "1W": "within a week", "1M": "within a month" };

const CURRENCY_SYMBOL: Record<string, string> = { EUR: "€", USD: "$" };
const pct0 = (p: number) => `${Math.round(p * 100)}%`;
const PROVIDER: Record<string, string> = { gemini: "Gemini" };

interface DecisionHeroProps {
  pair: PairMeta;
  forecast: LatestForecastResponse;
  selected: string;
  onSelect: (label: string) => void;
}

/** The sentence under the verdict, with the probability turned to the side the verdict favours. */
export function verdictSentence(ai: AiView | null, h: HorizonForecast): string {
  if (!ai) return "No model has proven an edge for this horizon.";
  const by = `by ${fmtShortDate(h.target_date)}`;
  const p = ai.prob_better_if_wait;
  const slight = ai.strength === "slight" ? ", a slight lean" : "";
  if (ai.lean === "sell_now") return `${pct0(1 - p)} chance the rate is lower ${by}${slight}.`;
  if (ai.lean === "wait") return `${pct0(p)} chance the rate is higher ${by}${slight}.`;
  return p >= 0.5
    ? `Close to even: ${pct0(p)} chance the rate is higher ${by}.`
    : `Close to even: ${pct0(1 - p)} chance the rate is lower ${by}.`;
}

export function aiTag(ai: AiView): string {
  const name = `${PROVIDER[ai.provider] ?? ai.provider} AI view`;
  const t = ai.track_record;
  if (t.promoted) return `${name}, proven on ${fmtInt(t.n_scored)} live forecasts`;
  return `${name}, not yet proven (${fmtInt(Math.min(t.n_scored, t.required))} of ${fmtInt(t.required)} checked)`;
}

function trackRecordText(ai: AiView): string {
  const t = ai.track_record;
  const parts = [
    t.n_scored < t.required
      ? `${fmtInt(t.n_scored)} of ${fmtInt(t.required)} live forecasts checked`
      : `${fmtInt(t.n_scored)} live forecasts checked`,
  ];
  if (t.n_scored > 0 && t.hit_rate !== null) parts.push(`hit rate ${fmtPct(t.hit_rate, 1)}`);
  if (t.n_scored > 0 && t.brier !== null) parts.push(`Brier ${fmtNum(t.brier, 3)} (0.25 is a coin flip)`);
  const head = parts.join(", ");
  if (t.promoted) return `${head}. Meets the same rule as the statistical models, so it decides the verdict.`;
  if (t.n_scored >= t.required) return `${head}. Does not meet the promotion rule, so it does not decide the verdict.`;
  return `${head}. Unproven, so it does not decide the verdict.`;
}

function statisticalLine(s: ConversionSignal | null, label: string): string {
  if (!s) return "No statistical signal";
  if (s.verdict_source === "ai") return "Verdict comes from the promoted AI view";
  if (s.action === "no_edge") return "No proven edge";
  return `${VERDICT[s.action]}, ${pct0(s.prob_better_if_wait)} chance of a better rate if you wait ${label}`;
}

function interestLine(s: ConversionSignal | null): string | null {
  if (!s || s.carry_pct_per_year === null) return null;
  const year = s.carry_pct_per_year;
  if (Math.abs(year) < 0.005) return `${s.receive} and ${s.sell} pay about the same`;
  const [more, less] = year > 0 ? [s.receive, s.sell] : [s.sell, s.receive];
  return `${more} pays ${fmtNum(Math.abs(year), 2)}%/yr more than ${less}`;
}

/**
 * The decision hero: one unmistakable answer for the chosen horizon. The verdict is the AI view's
 * own call (experimental, labelled with its live track record); without an AI view it reads
 * "No clear answer". The facts row carries the risk of waiting, the interest difference and the
 * statistical models' answer.
 */
export function DecisionHero({ pair, forecast, selected, onSelect }: DecisionHeroProps) {
  const [evidenceOpen, setEvidenceOpen] = useState(false);
  const evidenceId = useId();
  const horizons = [...forecast.horizons].sort((a, b) => a.days - b.days);
  const h = horizons.find((x) => x.label === selected) ?? horizons[horizons.length - 1];
  const ai = h.ai_view ?? null;
  const s = h.signal ?? null;
  const lean: SignalAction = ai?.lean ?? "no_edge";
  const sym = CURRENCY_SYMBOL[pair.base] ?? pair.base;
  const per = `${pair.quote} per ${sym}`;
  const lo = s?.downside_p10_rate ?? h.bands["80"]?.[0];
  const hi = s?.upside_p90_rate ?? h.bands["80"]?.[1];
  const interest = interestLine(s);
  const risks = h.meeting_risks ?? [];
  const wider = risks.filter((r) => r.level === "higher").map((r) => BANK_LABELS[r.bank] ?? r.bank);
  const Icon = lean === "sell_now" ? SellNowIcon : lean === "wait" ? WaitIcon : UnclearIcon;

  return (
    <section className="card hero" aria-labelledby="hero-question" data-testid="decision-hero" data-lean={lean}>
      <h1 id="hero-question" className="hero-question">
        Sell {pair.base} for {pair.quote} now?
      </h1>

      <div className="hero-need">
        <span className="hero-need-label" id="need-label">
          I need {pair.quote}
        </span>
        <div className="segmented" role="group" aria-labelledby="need-label">
          {horizons.map((x) => (
            <button
              key={x.days}
              type="button"
              className={x.label === h.label ? "seg seg-active" : "seg"}
              aria-pressed={x.label === h.label}
              onClick={() => onSelect(x.label)}
            >
              {NEED[x.label] ?? x.label}
            </button>
          ))}
        </div>
      </div>

      <div className={`verdict verdict-${lean}`} aria-live="polite">
        <span className="verdict-mark" aria-hidden="true">
          <Icon size={26} />
        </span>
        <p className="verdict-text" data-testid="verdict">
          {verdictText(lean, ai?.strength)}
        </p>
      </div>
      <p className="verdict-sentence" data-testid="verdict-sentence">
        {verdictSentence(ai, h)}
      </p>
      {ai && <p className="verdict-reasoning">{ai.reasoning}</p>}

      {ai && (
        <div className="hero-meta">
          <Confidence level={ai.confidence} />
          <button
            type="button"
            className="ai-tag"
            data-testid="ai-tag"
            aria-expanded={evidenceOpen}
            aria-controls={evidenceId}
            title={`${ai.model}, generated ${fmtDateTime(ai.generated_at)}`}
            onClick={() => setEvidenceOpen((o) => !o)}
          >
            {aiTag(ai)}
          </button>
        </div>
      )}

      {ai && evidenceOpen && (
        <dl className="hero-evidence" id={evidenceId} data-testid="hero-evidence">
          <div>
            <dt>AI model</dt>
            <dd>
              {ai.model}, prompt {ai.prompt_version}
            </dd>
          </div>
          <div>
            <dt>Generated</dt>
            <dd>
              <time dateTime={ai.generated_at}>{fmtDateTime(ai.generated_at)}</time>
            </dd>
          </div>
          <div>
            <dt>Live track record</dt>
            <dd data-testid="ai-track">{trackRecordText(ai)}</dd>
          </div>
          <div>
            <dt>AI expected rate</dt>
            <dd className="num">
              {fmtRate(ai.center, pair.decimals)} {per} by {fmtShortDate(h.target_date)} (80% range{" "}
              {fmtRate(ai.band80[0], pair.decimals)} to {fmtRate(ai.band80[1], pair.decimals)})
            </dd>
          </div>
          {s && (
            <div>
              <dt>Statistical models</dt>
              <dd>
                {MODEL_LABELS[s.model] ?? s.model}; {s.model_beats_random_walk ? "beats" : "does not beat"} the random
                walk over {fmtInt(s.n_obs)} backtest forecasts
              </dd>
            </div>
          )}
        </dl>
      )}

      {risks.length > 0 && <MeetingsInWindow risks={risks} days={h.days} />}

      <dl className="facts" data-testid="facts">
        {lo !== undefined && hi !== undefined && (
          <div data-testid="fact-wait">
            <dt>If you wait</dt>
            <dd>
              <span className="num">
                {fmtRate(lo, pair.decimals)} to {fmtRate(hi, pair.decimals)}
              </span>{" "}
              {per}, 80% range
              {wider.length > 0 && (
                <span className="fact-wider">
                  , likely wider around the {wider.join(" and ")} meeting{wider.length > 1 ? "s" : ""}
                </span>
              )}
            </dd>
          </div>
        )}
        {interest && (
          <div data-testid="fact-interest">
            <dt>Interest, at policy rates</dt>
            <dd>{interest}</dd>
          </div>
        )}
        <div data-testid="fact-stat">
          <dt>Statistical models</dt>
          <dd>{statisticalLine(s, h.label)}</dd>
        </div>
      </dl>
      <Disclaimer text={forecast.disclaimer} />
    </section>
  );
}

const PERIOD: Record<number, string> = { 1: "days", 5: "weeks", 21: "months" };

function lastSentence(text: string): string {
  const parts = text.split(/(?<=\.)\s+/).filter(Boolean);
  return parts[parts.length - 1] ?? text;
}

/** Meetings inside the chosen window: what last year's data says about each one. */
function MeetingsInWindow({ risks, days }: { risks: MeetingRiskOut[]; days: number }) {
  return (
    <section className="window-meetings" aria-label="Meetings in this window" data-testid="window-meetings">
      <p className="window-meetings-title">Meetings in this window</p>
      <ul>
        {risks.map((r) => {
          const name = BANK_LABELS[r.bank] ?? r.bank;
          const stats: string[] = [];
          if (r.reaction_vs_normal !== null) stats.push(`${fmtNum(r.reaction_vs_normal, 1)}x normal day`);
          if (r.band80_meeting_weeks !== null)
            stats.push(`range held ${Math.round(r.band80_meeting_weeks * 100)}% on ${name} ${PERIOD[days] ?? "weeks"} (target 80%)`);
          return (
            <li key={`${r.bank}-${r.date}`} className={`window-meeting level-${r.level}`} data-level={r.level}>
              <p className="window-meeting-head">
                <span className="bank-chip">
                  {name} {fmtShortDate(r.date)}
                </span>
                {r.level === "higher" && (
                  <strong className="window-swing">
                    <SwingIcon size={14} /> Bigger swing likely
                  </strong>
                )}
                {stats.length > 0 && <span className="window-stats num">{stats.join(", ")}</span>}
              </p>
              {/* The chip and the stats already carry the first sentences; show the takeaway, keep the
                  full sentence for screen readers and on hover. */}
              <p className="window-summary" title={r.summary}>
                <span aria-hidden="true">{lastSentence(r.summary)}</span>
                <span className="sr-only">{r.summary}</span>
              </p>
            </li>
          );
        })}
      </ul>
    </section>
  );
}

/** A small labelled 3-step meter. The word carries the level; the steps only echo it. */
function Confidence({ level }: { level: "low" | "medium" | "high" }) {
  const steps = { low: 1, medium: 2, high: 3 }[level];
  const word = level[0].toUpperCase() + level.slice(1);
  return (
    <span className="confidence" data-testid="confidence" data-level={level}>
      <span className="confidence-steps" aria-hidden="true">
        {[1, 2, 3].map((i) => (
          <span key={i} className={i <= steps ? "confidence-step is-on" : "confidence-step"} />
        ))}
      </span>
      <span>{word} confidence</span>
    </span>
  );
}
