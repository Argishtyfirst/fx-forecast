import { useState } from "react";
import type { ProviderQuote, QuoteChannel, QuotesResponse } from "../api/types";
import { fmtAgo, fmtDateTime, fmtMoney, fmtNum, fmtShortDate } from "../lib/format";
import type { QuoteGroup } from "../lib/useAmount";
import { ExternalIcon } from "./Icons";

const CHANNEL: Record<QuoteChannel, string> = {
  cash: "Cash",
  non_cash: "Card / account",
  card: "Card / account",
  online: "In the bank app",
  transfer: "Transfer",
};
const GROUP_CHANNELS: Record<QuoteGroup, QuoteChannel[]> = {
  account: ["non_cash", "online", "card", "transfer"],
  cash: ["cash"],
};

const signedPct = (v: number) => `${v > 0 ? "+" : v < 0 ? "−" : ""}${fmtNum(Math.abs(v), 2)}%`;

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
  if (/^\d{4}-\d{2}-\d{2}/.test(delivery)) return `arrives about ${fmtShortDate(delivery.slice(0, 10))}`;
  const t = delivery.replace(/^\s*should arrive:\s*/i, "").trim();
  return t ? t.charAt(0).toLowerCase() + t.slice(1) : null;
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
        Best place to convert today
      </h2>
      <p className="quotes-sub">
        For {amountText}. Indicative rates, check with the provider before converting
        {data?.as_of ? `. Updated ${fmtDateTime(data.as_of)}` : ""}.
      </p>

      <div className="segmented" role="group" aria-label="Where your money is">
        {(
          [
            ["account", "Money on an account"],
            ["cash", "Cash"],
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
          Provider rates could not be loaded right now.
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
        <p className="quotes-note">Provider rates are not available yet.</p>
      ) : (
        <>
          <ul className={loading ? "quotes-list is-refreshing" : "quotes-list"} data-testid="quotes-list">
            {shown.map((q, i) => (
              <QuoteRow key={`${q.provider}-${q.channel}`} q={q} best={i === 0} quote={quote} now={now} />
            ))}
          </ul>
          {local.length > 3 && (
            <button type="button" className="link-button" onClick={() => setAll((a) => !a)} aria-expanded={all}>
              {all ? "Show the top 3" : `Show all ${local.length}`}
            </button>
          )}
          {abroad.length > 0 && (
            <>
              <p className="quotes-group-title">Sending from abroad</p>
              <ul className="quotes-list" data-testid="quotes-abroad">
                {abroad.map((q) => (
                  <QuoteRow key={`${q.provider}-${q.channel}`} q={q} best={false} quote={quote} now={now} />
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
          : {u.reason}
        </p>
      ))}
      {data?.disclaimer && <p className="quotes-disclaimer">{data.disclaimer}</p>}
    </section>
  );
}

function QuoteRow({ q, best, quote, now }: { q: ProviderQuote; best: boolean; quote: string; now: Date }) {
  const arrives = deliveryText(q.delivery);
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
          {q.kind === "transfer" && <span className="tag quote-abroad">From abroad</span>}
        </span>
        <span className="quote-meta">
          {CHANNEL[q.channel] ?? q.channel}
          {arrives ? `, ${arrives}` : ""}
        </span>
        {q.note && <span className="quote-note">{q.note}</span>}
      </div>
      <div className="quote-what">
        <span className="quote-net num">{fmtMoney(q.net, quote)}</span>
        <span className="quote-meta num">
          {q.vs_reference_pct !== null ? `${signedPct(q.vs_reference_pct)} vs CBA, ` : ""}
          {q.stale ? `stale, ${fmtAgo(q.fetched_at, now)}` : fmtAgo(q.fetched_at, now)}
        </span>
      </div>
    </li>
  );
}
