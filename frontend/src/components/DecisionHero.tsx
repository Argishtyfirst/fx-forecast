import { useId, useState } from "react";
import type {
  AiView,
  ConversionSignal,
  HorizonForecast,
  LatestForecastResponse,
  MeetingRiskOut,
  SignalAction,
} from "../api/types";
import { pickText, t } from "../i18n";
import { BANK_LABELS, CURRENCY_SYMBOL, MODEL_LABELS, type PairMeta } from "../lib/constants";
import { addDays, fmtDateTime, fmtDayShort, fmtInt, fmtNum, fmtPct, fmtRange, fmtRate, fmtShortDate } from "../lib/format";
import { verdictText } from "../lib/verdict";
import { Disclaimer } from "./Disclaimer";
import { SellNowIcon, SwingIcon, UnclearIcon, WaitIcon } from "./Icons";

/** Plain-word verdicts. Wording carries the answer; the accent and the icon only reinforce it. */
export const VERDICT: Record<SignalAction, string> = new Proxy({} as Record<SignalAction, string>, {
  get: (_, k) => (k === "sell_now" || k === "wait" || k === "no_edge" ? t(`verdict.${k}`) : undefined),
});

/** The horizon control, phrased as the user's need. */
export const NEED: Record<string, string> = new Proxy({} as Record<string, string>, {
  get: (_, k) => (k === "1D" || k === "1W" || k === "1M" ? t(`need.${k}`) : undefined),
});

const pct0 = (p: number) => t("fmt.pct", { value: Math.round(p * 100) });
const PROVIDER: Record<string, string> = { gemini: "Gemini" };

interface DecisionHeroProps {
  pair: PairMeta;
  forecast: LatestForecastResponse;
  selected: string;
  onSelect: (label: string) => void;
}

/** The sentence under the verdict, with the probability turned to the side the verdict favours. */
export function verdictSentence(ai: AiView | null, h: HorizonForecast): string {
  if (!ai) return t("hero.noEdge");
  const date = fmtShortDate(h.target_date);
  const p = ai.prob_better_if_wait;
  const slight = ai.strength === "slight";
  if (ai.lean === "sell_now") return t(slight ? "hero.lowerSlight" : "hero.lower", { pct: pct0(1 - p), date });
  if (ai.lean === "wait") return t(slight ? "hero.higherSlight" : "hero.higher", { pct: pct0(p), date });
  return p >= 0.5 ? t("hero.evenHigher", { pct: pct0(p), date }) : t("hero.evenLower", { pct: pct0(1 - p), date });
}

/** The favoured side of a call, e.g. "Wait, 58%" or "Sell now, 54%". */
function callWords(lean: SignalAction, strength: AiView["strength"], p: number): string {
  const side = lean === "sell_now" ? 1 - p : lean === "wait" ? p : Math.max(p, 1 - p);
  return t("hero.call", { verdict: verdictText(lean, strength), pct: pct0(side) });
}

/** "Same call as yesterday (Wait, 58%)." or "Changed since yesterday: was Sell now, 54%." */
export function previousLine(ai: AiView): string | null {
  const prev = ai.previous;
  if (!prev) return null;
  const same = prev.lean === ai.lean && (prev.strength ?? "clear") === (ai.strength ?? "clear");
  const call = callWords(prev.lean, prev.strength, prev.prob_better_if_wait);
  // "Yesterday" only when the previous call is the calendar day before this call; weekends and
  // holidays name the day instead.
  const yesterday = ai.run_date !== undefined && prev.run_date === addDays(ai.run_date, -1);
  const day = fmtDayShort(prev.run_date);
  if (same) return yesterday ? t("hero.sameYesterday", { call }) : t("hero.sameOn", { day, call });
  return yesterday ? t("hero.changedYesterday", { call }) : t("hero.changedOn", { day, call });
}

/** "AI call from Fri 17 Oct" when the call predates the forecast (a weekend carry-over). */
function carriedOver(ai: AiView, asOf: string): string | null {
  return ai.run_date && ai.run_date < asOf ? t("hero.carried", { day: fmtDayShort(ai.run_date) }) : null;
}

export function aiTag(ai: AiView): string {
  const name = PROVIDER[ai.provider] ?? ai.provider;
  const r = ai.track_record;
  if (r.promoted) return t("hero.tagProven", { name, count: r.n_scored, n: fmtInt(r.n_scored) });
  return t("hero.tagUnproven", {
    name,
    done: fmtInt(Math.min(r.n_scored, r.required)),
    total: fmtInt(r.required),
  });
}

function trackRecordText(ai: AiView): string {
  const r = ai.track_record;
  const parts = [
    r.n_scored < r.required
      ? t("track.checkedOf", { done: fmtInt(r.n_scored), total: fmtInt(r.required) })
      : t("track.checked", { count: r.n_scored, n: fmtInt(r.n_scored) }),
  ];
  if (r.n_scored > 0 && r.hit_rate !== null) parts.push(t("track.hit", { pct: fmtPct(r.hit_rate, 1) }));
  if (r.n_scored > 0 && r.brier !== null) parts.push(t("track.brier", { value: fmtNum(r.brier, 3), coin: fmtNum(0.25, 2) }));
  const head = parts.join(", ");
  if (r.promoted) return `${head}${t("fmt.stop")} ${t("track.promoted")}`;
  if (r.n_scored >= r.required) return `${head}${t("fmt.stop")} ${t("track.notPromoted")}`;
  return `${head}${t("fmt.stop")} ${t("track.unproven")}`;
}

function statisticalLine(s: ConversionSignal | null, label: string): string {
  if (!s) return t("stat.none");
  if (s.verdict_source === "ai") return t("stat.fromAi");
  if (s.action === "no_edge") return t("stat.noEdge");
  return t("stat.lean", { verdict: VERDICT[s.action], pct: pct0(s.prob_better_if_wait), label });
}

function interestLine(s: ConversionSignal | null): string | null {
  if (!s || s.carry_pct_per_year === null) return null;
  const year = s.carry_pct_per_year;
  if (Math.abs(year) < 0.005) return t("hero.interestSame", { a: s.receive, b: s.sell });
  const [more, less] = year > 0 ? [s.receive, s.sell] : [s.sell, s.receive];
  return t("hero.interest", { more, less, pct: fmtNum(Math.abs(year), 2) });
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
  const per = t("hero.per", { quote: pair.quote, sym });
  const lo = s?.downside_p10_rate ?? h.bands["80"]?.[0];
  const hi = s?.upside_p90_rate ?? h.bands["80"]?.[1];
  const interest = interestLine(s);
  const risks = h.meeting_risks ?? [];
  const wider = risks.filter((r) => r.level === "higher").map((r) => BANK_LABELS[r.bank] ?? r.bank);
  const Icon = lean === "sell_now" ? SellNowIcon : lean === "wait" ? WaitIcon : UnclearIcon;

  return (
    <section className="card hero" aria-labelledby="hero-question" data-testid="decision-hero" data-lean={lean}>
      <h1 id="hero-question" className="hero-question">
        {t("hero.question", { base: pair.base, quote: pair.quote })}
      </h1>

      <div className="hero-need">
        <span className="hero-need-label" id="need-label">
          {t("hero.need", { quote: pair.quote })}
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
      {ai?.previous && (
        <p className="verdict-previous" data-testid="verdict-previous">
          {previousLine(ai)}
        </p>
      )}
      {ai && <p className="verdict-reasoning">{pickText(ai.reasoning_i18n, ai.reasoning)}</p>}

      {ai && (
        <div className="hero-meta">
          <Confidence level={ai.confidence} />
          <button
            type="button"
            className="ai-tag"
            data-testid="ai-tag"
            aria-expanded={evidenceOpen}
            aria-controls={evidenceId}
            title={`${t("hero.tagTitle", { model: ai.model, time: fmtDateTime(ai.generated_at) })}${
              carriedOver(ai, forecast.as_of) ? `${t("fmt.stop")} ${carriedOver(ai, forecast.as_of)}` : ""
            }`}
            onClick={() => setEvidenceOpen((o) => !o)}
          >
            {aiTag(ai)}
          </button>
        </div>
      )}

      {ai && evidenceOpen && (
        <dl className="hero-evidence" id={evidenceId} data-testid="hero-evidence">
          <div>
            <dt>{t("ev.model")}</dt>
            <dd>{t("ev.modelValue", { model: ai.model, prompt: ai.prompt_version })}</dd>
          </div>
          <div>
            <dt>{t("ev.generated")}</dt>
            <dd>
              <time dateTime={ai.generated_at}>{fmtDateTime(ai.generated_at)}</time>, {t("ev.onceADay")}
              {carriedOver(ai, forecast.as_of) && `${t("fmt.stop")} ${carriedOver(ai, forecast.as_of)}`}
              {(ai.revisions ?? 0) > 0 &&
                `${t("fmt.stop")} ${t(ai.run_date ? "ev.revisedOn" : "ev.revised", {
                  count: ai.revisions ?? 0,
                  date: ai.run_date ? fmtShortDate(ai.run_date) : "",
                })}`}
            </dd>
          </div>
          <div>
            <dt>{t("ev.track")}</dt>
            <dd data-testid="ai-track">{trackRecordText(ai)}</dd>
          </div>
          <div>
            <dt>{t("ev.expected")}</dt>
            <dd className="num">
              {t("ev.expectedValue", {
                rate: fmtRate(ai.center, pair.decimals),
                per,
                date: fmtShortDate(h.target_date),
                lo: fmtRate(ai.band80[0], pair.decimals),
                hi: fmtRate(ai.band80[1], pair.decimals),
              })}
            </dd>
          </div>
          {s && (
            <div>
              <dt>{t("ev.stat")}</dt>
              <dd>
                {t(s.model_beats_random_walk ? "ev.statBeats" : "ev.statNotBeats", {
                  model: MODEL_LABELS[s.model] ?? s.model,
                  n: fmtInt(s.n_obs),
                })}
              </dd>
            </div>
          )}
        </dl>
      )}

      {risks.length > 0 && <MeetingsInWindow risks={risks} days={h.days} pairLabel={pair.label} />}

      <dl className="facts" data-testid="facts">
        {lo !== undefined && hi !== undefined && (
          <div data-testid="fact-wait">
            <dt>{t("fact.wait")}</dt>
            <dd>
              <span className="num">{t("fact.waitValue", { range: fmtRange(lo, hi, pair.decimals), per })}</span>
              {wider.length > 0 && (
                <span className="fact-wider">
                  , {t("fact.wider", { count: wider.length, banks: wider.join(t("fmt.and")) })}
                </span>
              )}
            </dd>
          </div>
        )}
        {interest && (
          <div data-testid="fact-interest">
            <dt>{t("fact.interest")}</dt>
            <dd>{interest}</dd>
          </div>
        )}
        <div data-testid="fact-stat">
          <dt>{t("fact.stat")}</dt>
          <dd>{statisticalLine(s, h.label)}</dd>
        </div>
      </dl>
      <Disclaimer text={forecast.disclaimer} />
    </section>
  );
}

/** The meeting-risk sentence, built from the structured fields (the API's summary is English). */
export function meetingRiskText(r: MeetingRiskOut, pairLabel: string, days: number): string {
  const bank = BANK_LABELS[r.bank] ?? r.bank;
  const parts: string[] = [];
  if (r.reaction_vs_normal !== null)
    parts.push(
      t("risk.moved", { bank, pair: pairLabel, ratio: fmtNum(r.reaction_vs_normal, 1), count: r.meetings_last_year, n: r.meetings_last_year }),
    );
  if (r.band80_meeting_weeks !== null)
    parts.push(t(`risk.held.${days === 1 ? "1D" : days === 5 ? "1W" : "1M"}`, { bank, pct: Math.round(r.band80_meeting_weeks * 100) }));
  parts.push(t(`risk.level.${r.level}`));
  return parts.join(" ");
}

/** Meetings inside the chosen window: what last year's data says about each one. */
function MeetingsInWindow({ risks, days, pairLabel }: { risks: MeetingRiskOut[]; days: number; pairLabel: string }) {
  const period = days === 1 ? "1D" : days === 5 ? "1W" : "1M";
  return (
    <section className="window-meetings" aria-label={t("risk.title")} data-testid="window-meetings">
      <p className="window-meetings-title">{t("risk.title")}</p>
      <ul>
        {risks.map((r) => {
          const name = BANK_LABELS[r.bank] ?? r.bank;
          const stats: string[] = [];
          if (r.reaction_vs_normal !== null) stats.push(t("risk.statRatio", { ratio: fmtNum(r.reaction_vs_normal, 1) }));
          if (r.band80_meeting_weeks !== null)
            stats.push(t(`risk.statHeld.${period}`, { pct: Math.round(r.band80_meeting_weeks * 100), bank: name }));
          const full = meetingRiskText(r, pairLabel, days);
          return (
            <li key={`${r.bank}-${r.date}`} className={`window-meeting level-${r.level}`} data-level={r.level}>
              <p className="window-meeting-head">
                <span className="bank-chip">
                  {name} {fmtShortDate(r.date)}
                </span>
                {r.level === "higher" && (
                  <strong className="window-swing">
                    <SwingIcon size={14} /> {t("risk.bigger")}
                  </strong>
                )}
                {stats.length > 0 && <span className="window-stats num">{stats.join(", ")}</span>}
              </p>
              {/* The chip and the stats carry the numbers; show the takeaway, keep the full
                  sentence for screen readers and on hover. */}
              <p className="window-summary" title={full}>
                <span aria-hidden="true">{t(`risk.level.${r.level}`)}</span>
                <span className="sr-only">{full}</span>
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
  const word = t(`conf.${level}`);
  return (
    <span className="confidence" data-testid="confidence" data-level={level}>
      <span className="confidence-steps" aria-hidden="true">
        {[1, 2, 3].map((i) => (
          <span key={i} className={i <= steps ? "confidence-step is-on" : "confidence-step"} />
        ))}
      </span>
      <span>{word}</span>
    </span>
  );
}
