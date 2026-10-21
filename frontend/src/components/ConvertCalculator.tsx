import { useEffect, useId, useRef, useState } from "react";
import type { HorizonForecast, ProviderQuote } from "../api/types";
import type { PairMeta } from "../lib/constants";
import { fmtMoney, fmtNum, fmtRate, fmtShortDate, MAX_AMOUNT, parseAmount } from "../lib/format";

const CURRENCY_WORD: Record<string, string> = { EUR: "euros", USD: "dollars" };

interface ConvertCalculatorProps {
  pair: PairMeta;
  horizon: HorizonForecast;
  spot: number;
  amount: number;
  onAmount: (n: number) => void;
  /** Best provider quote for this amount (AMD pairs), or null. */
  best: ProviderQuote | null;
}

const signedPct = (v: number) => `${v > 0 ? "+" : v < 0 ? "−" : ""}${fmtNum(Math.abs(v), 2)}%`;

/** "My euros in AMD": what a typed amount is worth now, at the best place, and if you wait. */
export function ConvertCalculator({ pair, horizon, spot, amount, onAmount, best }: ConvertCalculatorProps) {
  const inputId = useId();
  const [draft, setDraft] = useState(() => formatDraft(amount));
  // The typed text is the user's: never rewrite it while the field has focus. It is formatted on
  // first load, on a currency switch (the stored amount changes) and on blur.
  const focused = useRef(false);
  useEffect(() => {
    if (!focused.current) setDraft(formatDraft(amount));
  }, [amount, pair.base]);
  const parsed = parseAmount(draft);
  const hint = !draft.trim()
    ? "Enter an amount like 1 500"
    : parsed === null || parsed <= 0
      ? "Enter an amount like 1 500"
      : parsed > MAX_AMOUNT
        ? "Up to 10 000 000"
        : null;
  const base = pair.base;
  const quote = pair.quote;
  const band = horizon.bands["80"];
  const carry = horizon.signal?.carry_amount ?? null;
  const by = fmtShortDate(horizon.target_date);
  const refName = quote === "AMD" ? "CBA rate" : "ECB rate";

  return (
    <section className="card convert" aria-labelledby="convert-title" data-testid="convert">
      <h2 id="convert-title" className="card-title">
        My {CURRENCY_WORD[base] ?? base} in {quote}
      </h2>
      <div className="convert-input">
        <label htmlFor={inputId}>Amount in {base}</label>
        <input
          id={inputId}
          type="text"
          inputMode="decimal"
          autoComplete="off"
          value={draft}
          onFocus={() => {
            focused.current = true;
          }}
          onChange={(e) => {
            setDraft(e.target.value);
            const n = parseAmount(e.target.value);
            // Only a valid amount the API accepts is stored and sent.
            if (n !== null && n > 0 && n <= MAX_AMOUNT) onAmount(n);
          }}
          onBlur={() => {
            focused.current = false;
            const n = parseAmount(draft);
            setDraft(formatDraft(n !== null && n > 0 && n <= MAX_AMOUNT ? n : amount));
          }}
          aria-invalid={hint !== null}
          aria-describedby={`${inputId}-help`}
        />
        <span id={`${inputId}-help`} className={hint ? "convert-help is-hint" : "convert-help"}>
          {hint ?? `1 ${base} = ${fmtRate(spot, pair.decimals)} ${quote}`}
        </span>
      </div>

      <dl className="convert-rows">
        <div data-testid="convert-now">
          <dt>Now, at the {refName}</dt>
          <dd>
            <span className="convert-value num">{fmtMoney(amount * spot, quote)}</span>
          </dd>
        </div>
        {best && (
          <div data-testid="convert-best">
            <dt>Best place today</dt>
            <dd>
              <span className="convert-value num">{fmtMoney(best.net, quote)}</span>{" "}
              <span className="convert-sub">
                at {best.name}
                {best.kind === "transfer" ? " (from abroad)" : ""}
                {best.vs_reference_pct !== null ? `, ${signedPct(best.vs_reference_pct)} vs the ${refName}` : ""}
              </span>
            </dd>
          </div>
        )}
        {band && (
          <div data-testid="convert-wait">
            <dt>If you wait until {by}</dt>
            <dd>
              Likely between <span className="num">{fmtMoney(amount * band[0], quote)}</span> and{" "}
              <span className="num">{fmtMoney(amount * band[1], quote)}</span> by {by} (8 in 10 chance)
            </dd>
          </div>
        )}
        {carry !== null && (
          <div data-testid="convert-carry">
            <dt>Interest difference</dt>
            <dd>
              {carry >= 0 ? (
                <>
                  Holding {quote} instead of {base} earns about{" "}
                  <span className="num">{fmtMoney(amount * carry, quote)}</span> more by {by}, at policy rates
                </>
              ) : (
                <>
                  Holding {base} instead of {quote} earns about{" "}
                  <span className="num">{fmtMoney(Math.abs(amount * carry), quote)}</span> more by {by}, at policy
                  rates
                </>
              )}
            </dd>
          </div>
        )}
      </dl>
    </section>
  );
}

function formatDraft(n: number): string {
  const [int, dec] = String(Math.round(n * 100) / 100).split(".");
  return int.replace(/\B(?=(\d{3})+(?!\d))/g, " ") + (dec ? `.${dec}` : "");
}
