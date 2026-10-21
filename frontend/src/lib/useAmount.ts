import { useCallback, useEffect, useState } from "react";
import { MAX_AMOUNT } from "./format";

const DEFAULT_AMOUNT = 1000;
const keyOf = (currency: string) => `fxf-amount-${currency}`;
/** An amount the API accepts: positive and at most 10 000 000. */
const valid = (n: number) => Number.isFinite(n) && n > 0 && n <= MAX_AMOUNT;

function read(currency: string): number {
  try {
    const v = Number(window.localStorage.getItem(keyOf(currency)));
    return valid(v) ? v : DEFAULT_AMOUNT;
  } catch {
    return DEFAULT_AMOUNT;
  }
}

/** The amount to convert, remembered per base currency ("fxf-amount-EUR"). */
export function useAmount(currency: string): [number, (n: number) => void] {
  const [amount, setAmount] = useState(() => read(currency));
  useEffect(() => setAmount(read(currency)), [currency]);
  const set = useCallback(
    (n: number) => {
      if (!valid(n)) return;
      setAmount(n);
      try {
        window.localStorage.setItem(keyOf(currency), String(n));
      } catch {
        // Storage blocked: the amount still holds for this session.
      }
    },
    [currency],
  );
  return [amount, set];
}

/** The value after it has stopped changing for `ms`. */
export function useDebounced<T>(value: T, ms = 400): T {
  const [v, setV] = useState(value);
  useEffect(() => {
    const id = window.setTimeout(() => setV(value), ms);
    return () => window.clearTimeout(id);
  }, [value, ms]);
  return v;
}

export type QuoteGroup = "account" | "cash";
const GROUP_KEY = "fxf-quote-channel";

/** "Money on an account" or "Cash", remembered across visits. */
export function useQuoteGroup(): [QuoteGroup, (g: QuoteGroup) => void] {
  const [group, setGroup] = useState<QuoteGroup>(() => {
    try {
      return window.localStorage.getItem(GROUP_KEY) === "cash" ? "cash" : "account";
    } catch {
      return "account";
    }
  });
  const set = useCallback((g: QuoteGroup) => {
    setGroup(g);
    try {
      window.localStorage.setItem(GROUP_KEY, g);
    } catch {
      // Storage blocked: the choice still holds for this session.
    }
  }, []);
  return [group, set];
}
