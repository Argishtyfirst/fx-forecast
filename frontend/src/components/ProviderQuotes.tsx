import { useState } from "react";
import type { ProviderQuote, QuoteChannel, QuotesResponse } from "../api/types";
import { getLang, t } from "../i18n";
import { fmtAgo, fmtDateTime, fmtMoney, fmtShortDate, fmtSignedPct } from "../lib/format";
import type { QuoteGroup } from "../lib/useAmount";
import { ExternalIcon } from "./Icons";

const CHANNEL: Record<QuoteChannel, () => string> = {
  cash: () => t("quote.channel.cash"),
  non_cash: () => t("quote.channel.account"),
  card: () => t("quote.channel.account"),
  online: () => t("quote.channel.online"),
  transfer: () => t("quote.channel.transfer"),
};
const GROUP_CHANNELS: Record<QuoteGroup, QuoteChannel[]> = {
  account: ["non_cash", "online", "card", "transfer"],
  cash: ["cash"],
};

const REGION: Record<string, "quote.from.EUR" | "quote.from.USD" | "quote.from.GBP" | "quote.from.RUB"> = {
  EUR: "quote.from.EUR",
  USD: "quote.from.USD",
  GBP: "quote.from.GBP",
  RUB: "quote.from.RUB",
};

/**
 * The provider's note in the active language, built from provider, channel and pair (the API's
 * notes are English). Unknown English notes are shown only in English.
 */
export function quoteNote(q: ProviderQuote, base: string): string | null {
  const from = t(REGION[base] ?? "quote.from.EUR");
  if (q.provider === "wise") return t("quote.note.wise", { from });
  if (q.provider === "paysend") return t("quote.note.paysend", { from });
  if (q.channel === "online") return t("quote.note.online", { name: q.name });
  return getLang() === "en" ? q.note : null;
}

function unavailableReason(provider: string, reason: string): string {
  if (provider === "revolut") return t("quote.unavailable.revolut");
  return getLang() === "en" ? reason : t("quote.unavailable.generic");
}

/**
 * One row per provider within the chosen group (its best channel), fresh quotes first, then by
 * what you receive, then by name so ties read in a stable order.
 */
export function rankQuotes(quotes: ProviderQuote[], group: QuoteGroup): ProviderQuote[] {
  const allowed = GROUP_CHANNELS[group];
  const best = new Map<string, ProviderQuote>();
  for (const q of quotes) {
    if (!allowed.includes(q.channel)) continue;
    const cur = best.get(q.provider);
    if (!cur || Number(q.stale) < Number(cur.stale) || (q.stale === cur.stale && q.net > cur.net)) best.set(q.provider, q);
  }
  return [...best.values()].sort(
    (a, b) => Number(a.stale) - Number(b.stale) || b.net - a.net || a.name.localeCompare(b.name),
  );
}

/** "arrives about 28 Oct" for an ISO date; free text without its "Should arrive:" prefix. */
export function deliveryText(delivery: string | null | undefined): string | null {
  if (!delivery) return null;
  if (/^\d{4}-\d{2}-\d{2}/.test(delivery)) return t("quote.arrives", { date: fmtShortDate(delivery.slice(0, 10)) });
  const text = delivery.replace(/^\s*should arrive:\s*/i, "").trim();
  if (!text) return null;
  if (/few minutes/i.test(text)) return t("quote.minutes");
  return getLang() === "en" ? text.charAt(0).toLowerCase() + text.slice(1) : null;
}

interface ProviderQuotesProps {
  data: QuotesResponse | undefined;
  loading: boolean;
  error: Error | undefined;
  amount: number;
  base: string;
  group: QuoteGroup;
  onGroup: (g: QuoteGroup) => void;
}

/** "Best place to convert today": provider rates for the typed amount, best first (AMD pairs). */
export function ProviderQuotes({ data, loading, error, amount, base, group, onGroup }: ProviderQuotesProps) {
  const [all, setAll] = useState(false);
  const now = new Date();
  const ranked = rankQuotes(data?.quotes ?? [], group);
  // Local boards first; transfers from abroad are a different situation, so they get their own
  // short list under the top 3 and the gap between the two stays visible.
  const local = ranked.filter((q) => q.kind !== "transfer");
  const abroad = ranked.filter((q) => q.kind === "transfer");
  const shown = all ? local : local.slice(0, 3);
  const quote = data?.pair.slice(3) ?? "AMD";
  const amountText = Number.isInteger(amount) ? fmtMoney(amount, "AMD").replace(" AMD", ` ${base}`) : fmtMoney(amount, base);

  return (
    <section className="card quotes" aria-labelledby="quotes-title" data-testid="provider-quotes">
      <h2 id="quotes-title" className="card-title">
        {t("quote.title")}
      </h2>
      <p className="quotes-sub">
        {t("quote.sub", { amount: amountText })}
        {data?.as_of ? ` ${t("quote.updated", { time: fmtDateTime(data.as_of) })}` : ""}
      </p>

      <div className="segmented" role="group" aria-label={t("quote.groupAria")}>
        {(
          [
            ["account", t("quote.group.account")],
            ["cash", t("quote.group.cash")],
          ] as const
        ).map(([g, label]) => (
          <button
            key={g}
            type="button"
            className={group === g ? "seg seg-active" : "seg"}
            aria-pressed={group === g}
            onClick={() => {
              onGroup(g);
              setAll(false);
            }}
          >
            {label}
          </button>
        ))}
      </div>

      {error ? (
        <p className="quotes-note" role="alert">
          {t("quote.error")}
        </p>
      ) : !data && loading ? (
        <ul className="quotes-list" aria-busy="true">
          {[0, 1, 2].map((i) => (
            <li key={i} className="quote-row quote-skeleton" aria-hidden="true">
              <span />
              <span />
            </li>
          ))}
        </ul>
      ) : ranked.length === 0 ? (
        <p className="quotes-note">{t("quote.empty")}</p>
      ) : (
        <>
          <ul className={loading ? "quotes-list is-refreshing" : "quotes-list"} data-testid="quotes-list">
            {shown.map((q, i) => (
              <QuoteRow key={`${q.provider}-${q.channel}`} q={q} best={i === 0} quote={quote} base={base} now={now} />
            ))}
          </ul>
          {local.length > 3 && (
            <button type="button" className="link-button" onClick={() => setAll((a) => !a)} aria-expanded={all}>
              {all ? t("quote.showTop") : t("quote.showAll", { count: local.length })}
            </button>
          )}
          {abroad.length > 0 && (
            <>
              <p className="quotes-group-title">{t("quote.abroadTitle")}</p>
              <ul className="quotes-list" data-testid="quotes-abroad">
                {abroad.map((q) => (
                  <QuoteRow key={`${q.provider}-${q.channel}`} q={q} best={false} quote={quote} base={base} now={now} />
                ))}
              </ul>
            </>
          )}
        </>
      )}
      {(data?.unavailable ?? []).map((u) => (
        <p key={u.provider} className="quotes-unavailable">
          {u.url ? (
            <a href={u.url} target="_blank" rel="noreferrer">
              {u.name}
            </a>
          ) : (
            u.name
          )}
          : {unavailableReason(u.provider, u.reason)}
        </p>
      ))}
      {data && <p className="quotes-disclaimer">{t("quote.disclaimer")}</p>}
    </section>
  );
}

function QuoteRow({ q, best, quote, base, now }: { q: ProviderQuote; best: boolean; quote: string; base: string; now: Date }) {
  const arrives = deliveryText(q.delivery);
  const note = quoteNote(q, base);
  return (
    <li className={best ? "quote-row is-best" : "quote-row"}>
      <div className="quote-who">
        <span className="quote-title">
          {q.url ? (
            <a href={q.url} target="_blank" rel="noreferrer" className="quote-name">
              {q.name} <ExternalIcon size={12} />
            </a>
          ) : (
            <span className="quote-name">{q.name}</span>
          )}
          {q.kind === "transfer" && <span className="tag quote-abroad">{t("quote.fromAbroad")}</span>}
        </span>
        <span className="quote-meta">
          {CHANNEL[q.channel]?.() ?? q.channel}
          {arrives ? `, ${arrives}` : ""}
        </span>
        {note && <span className="quote-note">{note}</span>}
      </div>
      <div className="quote-what">
        <span className="quote-net num">{fmtMoney(q.net, quote)}</span>
        <span className="quote-meta num">
          {q.vs_reference_pct !== null ? `${t("quote.vsCba", { pct: fmtSignedPct(q.vs_reference_pct) })}, ` : ""}
          {q.stale ? t("quote.staleAgo", { ago: fmtAgo(q.fetched_at, now) }) : fmtAgo(q.fetched_at, now)}
        </span>
      </div>
    </li>
  );
}
