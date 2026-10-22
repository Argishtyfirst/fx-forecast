import { useEffect, useId, useRef, useState } from "react";
import type { HorizonForecast, ProviderQuote } from "../api/types";
import type { PairMeta } from "../lib/constants";
import { getLang, getLocale, t, tMaybe } from "../i18n";
import { fmtMoney, fmtRate, fmtShortDate, fmtSignedPct, MAX_AMOUNT, parseAmount } from "../lib/format";

interface ConvertCalculatorProps {
  pair: PairMeta;
  horizon: HorizonForecast;
  spot: number;
  amount: number;
  onAmount: (n: number) => void;
  /** Best provider quote for this amount (AMD pairs), or null. */
  best: ProviderQuote | null;
}


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
  const hint =
    !draft.trim() || parsed === null || parsed <= 0
      ? t("calc.hintEnter")
      : parsed > MAX_AMOUNT
        ? t("calc.hintMax")
        : null;
  const base = pair.base;
  const quote = pair.quote;
  const band = horizon.bands["80"];
  const carry = horizon.signal?.carry_amount ?? null;
  const by = fmtShortDate(horizon.target_date);
  const refName = quote === "AMD" || base === "RUB" ? t("calc.refCba") : t("calc.refEcb");

  return (
    <section className="card convert" aria-labelledby="convert-title" data-testid="convert">
      <h2 id="convert-title" className="card-title">
        {tMaybe(`calc.title.${base}${quote}`) ?? `${base} → ${quote}`}
      </h2>
      <div className="convert-input">
        <label htmlFor={inputId}>{t("calc.amountIn", { currency: base })}</label>
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
          <dt>{t("calc.now", { ref: refName })}</dt>
          <dd>
            <span className="convert-value num">{fmtMoney(amount * spot, quote)}</span>
          </dd>
        </div>
        {best && (
          <div data-testid="convert-best">
            <dt>{t("calc.best")}</dt>
            <dd>
              <span className="convert-value num">{fmtMoney(best.net, quote)}</span>{" "}
              <span className="convert-sub">
                {t(best.kind === "transfer" ? "calc.atAbroad" : "calc.at", { name: best.name })}
                {best.vs_reference_pct !== null
                  ? `, ${t("calc.vsRef", { pct: fmtSignedPct(best.vs_reference_pct), ref: refName })}`
                  : ""}
              </span>
            </dd>
          </div>
        )}
        {band && (
          <div data-testid="convert-wait">
            <dt>{t("calc.waitUntil", { date: by })}</dt>
            <dd className="num">
              {t("calc.likely", { lo: fmtMoney(amount * band[0], quote), hi: fmtMoney(amount * band[1], quote), date: by })}
            </dd>
          </div>
        )}
        {carry !== null && (
          <div data-testid="convert-carry">
            <dt>{t("calc.interest")}</dt>
            <dd>
              {t("calc.carry", {
                more: carry >= 0 ? quote : base,
                less: carry >= 0 ? base : quote,
                amount: fmtMoney(Math.abs(amount * carry), quote),
                date: by,
              })}
            </dd>
          </div>
        )}
      </dl>
    </section>
  );
}

/** The amount as an editable string: plain spaces between thousands, the locale's decimal mark. */
function formatDraft(n: number): string {
  return new Intl.NumberFormat(getLocale(), { maximumFractionDigits: 2 })
    .formatToParts(n)
    .map((p) => (p.type === "group" ? " " : p.type === "decimal" && getLang() === "hy" ? "," : p.value))
    .join("");
}
