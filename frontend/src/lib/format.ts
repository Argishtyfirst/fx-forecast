/**
 * Number and date formatting. Rates keep their source precision; nothing is rounded into a promise.
 * Visible text uses no en or em dashes: ranges read "a to b" and missing values read "n/a".
 */

import { getLang, getLocale, t } from "../i18n";

/** "n/a" in the active language. */
export function na(): string {
  return t("fmt.na");
}
/** @deprecated use na(); kept for call sites that only need a placeholder string. */
export const NA = "n/a";

const MINUS = "\u2212";
const THIN = "\u202f"; // narrow no-break space for digit grouping

const numberFormats = new Map<string, Intl.NumberFormat>();
function nf(digits: number, grouping = false): Intl.NumberFormat {
  const key = `${getLocale()}|${digits}|${grouping}`;
  let f = numberFormats.get(key);
  if (!f) {
    f = new Intl.NumberFormat(getLocale(), {
      minimumFractionDigits: digits,
      maximumFractionDigits: digits,
      useGrouping: grouping,
    });
    numberFormats.set(key, f);
  }
  return f;
}

/** A number in the active locale with a true minus sign; grouping uses a thin space. */
function num(x: number, digits: number, grouping = false): string {
  const parts = nf(digits, grouping).formatToParts(x);
  return parts
    .map((p) =>
      p.type === "minusSign" ? MINUS : p.type === "group" ? THIN : p.type === "decimal" && isHy() ? "," : p.value,
    )
    .join("");
}

const bad = (x: number | null | undefined): x is null | undefined => x === null || x === undefined || !Number.isFinite(x);

export function fmtRate(x: number | null | undefined, decimals: number): string {
  if (bad(x)) return na();
  return num(x, decimals);
}

export function fmtRange(lo: number, hi: number, decimals: number): string {
  return t("fmt.range", { lo: fmtRate(lo, decimals), hi: fmtRate(hi, decimals) });
}

/** Signed number with a true minus sign, e.g. "+12.5", "\u22124", "0". */
export function fmtSigned(x: number | null | undefined, digits = 0): string {
  if (bad(x)) return na();
  const r = Number(x.toFixed(digits));
  if (r === 0) return num(0, digits);
  return `${r > 0 ? "+" : MINUS}${num(Math.abs(r), digits)}`;
}

export function fmtBps(x: number | null | undefined, signed = true): string {
  if (bad(x)) return na();
  const digits = Number.isInteger(Math.round(x * 10) / 10) ? 0 : 1;
  return t("fmt.bps", { value: signed ? fmtSigned(x, digits) : num(x, digits) });
}

export function fmtPct(x: number | null | undefined, digits = 1): string {
  if (bad(x)) return na();
  return t("fmt.pct", { value: num(x * 100, digits) });
}

/** A value that is already in percent (policy rates). */
export function fmtPercentValue(x: number | null | undefined, digits = 2): string {
  if (bad(x)) return na();
  return t("fmt.pct", { value: num(x, digits) });
}

/** A signed value already in percent: "+0.42%", "\u22121.59%". */
export function fmtSignedPct(x: number | null | undefined, digits = 2): string {
  if (bad(x)) return na();
  return t("fmt.pct", { value: fmtSigned(x, digits) });
}

export function fmtNum(x: number | null | undefined, digits = 2): string {
  if (bad(x)) return na();
  return num(x, digits);
}

export function fmtInt(x: number | null | undefined): string {
  if (bad(x)) return na();
  return num(Math.round(x), 0, true);
}

// --- dates ---------------------------------------------------------------------------------

/** Parse "YYYY-MM-DD" as a UTC calendar date (no timezone drift). */
export function parseDate(iso: string): Date {
  return new Date(`${iso.slice(0, 10)}T00:00:00Z`);
}

export function isoDate(d: Date): string {
  return d.toISOString().slice(0, 10);
}

export function addDays(iso: string, n: number): string {
  const d = parseDate(iso);
  d.setUTCDate(d.getUTCDate() + n);
  return isoDate(d);
}

export function daysBetween(a: string, b: string): number {
  return Math.round((parseDate(b).getTime() - parseDate(a).getTime()) / 86_400_000);
}

// English keeps its own short month names ("Sep", not en-GB's "Sept"); hy and ru use Intl.
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const WEEKDAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
const isEn = () => getLang() === "en";
// Armenian by hand: browsers often ship without hy-AM date data and fall back to English.
const isHy = () => getLang() === "hy";
const HY_MONTHS = ["հնվ", "փտվ", "մրտ", "ապր", "մյս", "հնս", "հլս", "օգս", "սեպ", "հոկ", "նոյ", "դեկ"];
const HY_WEEKDAYS = ["կիր", "երկ", "երք", "չրք", "հնգ", "ուրբ", "շբթ"];

/** "28 Oct" for a day and a 0-based month, in the active language. */
export function fmtDayMonth(day: number, month: number): string {
  if (isEn()) return `${day} ${MONTHS[month]}`;
  if (isHy()) return `${day} ${HY_MONTHS[month]}`;
  return dtf({ day: "numeric", month: "short", timeZone: "UTC" }).format(new Date(Date.UTC(2000, month, day)));
}
const dtf = (opts: Intl.DateTimeFormatOptions) => new Intl.DateTimeFormat(getLocale(), opts);

/** "21 Oct 2026" */
export function fmtDate(iso: string): string {
  const d = parseDate(iso);
  if (isEn()) return `${d.getUTCDate()} ${MONTHS[d.getUTCMonth()]} ${d.getUTCFullYear()}`;
  if (isHy()) return `${d.getUTCDate()} ${HY_MONTHS[d.getUTCMonth()]} ${d.getUTCFullYear()} թ.`;
  return dtf({ day: "numeric", month: "short", year: "numeric", timeZone: "UTC" }).format(d);
}
/** "21 Oct" */
export function fmtShortDate(iso: string): string {
  const d = parseDate(iso);
  return fmtDayMonth(d.getUTCDate(), d.getUTCMonth());
}
/** "Wed, 21 Oct 2026" */
export function fmtWeekdayDate(iso: string): string {
  const d = parseDate(iso);
  if (isEn()) return `${WEEKDAYS[d.getUTCDay()]}, ${fmtDate(iso)}`;
  if (isHy()) return `${HY_WEEKDAYS[d.getUTCDay()]}, ${fmtDate(iso)}`;
  return dtf({ weekday: "short", day: "numeric", month: "short", year: "numeric", timeZone: "UTC" }).format(d);
}
/** "Fri 17 Oct" */
export function fmtDayShort(iso: string): string {
  const d = parseDate(iso);
  if (isEn()) return `${WEEKDAYS[d.getUTCDay()]} ${d.getUTCDate()} ${MONTHS[d.getUTCMonth()]}`;
  if (isHy()) return `${HY_WEEKDAYS[d.getUTCDay()]} ${d.getUTCDate()} ${HY_MONTHS[d.getUTCMonth()]}`;
  return dtf({ weekday: "short", day: "numeric", month: "short", timeZone: "UTC" }).format(d);
}
/** "Oct" */
export function fmtMonth(iso: string): string {
  const d = parseDate(iso);
  if (isEn()) return MONTHS[d.getUTCMonth()];
  if (isHy()) return HY_MONTHS[d.getUTCMonth()];
  return dtf({ month: "short", timeZone: "UTC" }).format(d);
}

function hm(d: Date): string {
  return `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
}
function tzName(d: Date): string {
  const parts = new Intl.DateTimeFormat(getLocale(), { timeZoneName: "short" }).formatToParts(d);
  return parts.find((p) => p.type === "timeZoneName")?.value ?? "";
}

/** A UTC timestamp in the viewer's local time: "16 Oct 2026, 17:20 CEST". */
export function fmtDateTime(iso: string | null | undefined): string {
  if (!iso) return t("fmt.never");
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  const local = isoDate(new Date(d.getTime() - d.getTimezoneOffset() * 60_000));
  const tz = tzName(d);
  return `${fmtDate(local)}, ${hm(d)}${tz ? ` ${tz}` : ""}`;
}

/** Compact local time for status rows: "17:16" today, "16 Oct 17:20" otherwise. */
export function fmtCompactTime(iso: string | null | undefined, now: Date): string {
  if (!iso) return t("fmt.never");
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  const sameDay = d.toDateString() === now.toDateString();
  const local = isoDate(new Date(d.getTime() - d.getTimezoneOffset() * 60_000));
  return sameDay ? hm(d) : `${fmtShortDate(local)} ${hm(d)}`;
}

const HY_UNIT: Record<"minute" | "hour" | "day", string> = { minute: "րոպե", hour: "ժամ", day: "օր" };
const rtf = () => ({
  format(n: number, unit: "minute" | "hour" | "day"): string {
    if (isHy()) {
      if (unit === "day" && n === 0) return "այսօր";
      if (unit === "day" && n === 1) return "վաղը";
      if (unit === "day" && n === -1) return "երեկ";
      return n < 0 ? `${-n} ${HY_UNIT[unit]} առաջ` : `${n} ${HY_UNIT[unit]} հետո`;
    }
    return new Intl.RelativeTimeFormat(getLocale(), { numeric: "auto" }).format(n, unit);
  },
});

/** "5 days ago", "3 hours ago", relative to `now` (the health check time, so tests are stable). */
export function fmtAgo(iso: string | null | undefined, now: Date): string {
  if (!iso) return t("fmt.never");
  const ms = now.getTime() - new Date(iso).getTime();
  if (!Number.isFinite(ms)) return "";
  const min = Math.round(ms / 60_000);
  if (min < 1) return t("fmt.justNow");
  if (min < 60) return rtf().format(-min, "minute");
  const h = Math.round(min / 60);
  if (h < 48) return rtf().format(-h, "hour");
  return rtf().format(-Math.round(h / 24), "day");
}

export function fmtDaysUntil(n: number | null | undefined): string {
  if (n === null || n === undefined) return na();
  return rtf().format(n, "day");
}

export function titleCase(s: string): string {
  return s.replace(/_/g, " ").replace(/^\w/, (c) => c.toUpperCase());
}

/** Money with thin digit grouping: AMD without decimals ("425 300 AMD"), others with 2. */
export function fmtMoney(value: number | null | undefined, currency: string): string {
  if (bad(value)) return na();
  const digits = currency === "AMD" ? 0 : 2;
  return `${num(value, digits, true)} ${currency}`;
}

/** The largest amount the API accepts. */
export const MAX_AMOUNT = 10_000_000;

/**
 * Parse a typed amount. Accepts digits, spaces (also thin and no-break) and separators:
 * "1 000", "1,000" and "1.000" are 1000; "1,000.50" and "1.000,50" are 1000.5; a leading 0
 * group is never a thousands group ("0.250" is 0.25). Anything else, such as "1e3", "0x10",
 * mixed or misplaced separators, returns null.
 */
export function parseAmount(text: string): number | null {
  const t = text.replace(/[\s\u00a0\u202f]/g, "");
  if (!t || !/^[\d.,]+$/.test(t)) return null;
  const commas = (t.match(/,/g) ?? []).length;
  const dots = (t.match(/\./g) ?? []).length;
  const grouped = (s: string, sep: string) =>
    new RegExp(`^[1-9]\\d{0,2}(\\${sep}\\d{3})+$`).test(s) ? s.split(sep).join("") : null;
  let normal: string | null;
  if (commas === 0 && dots === 0) normal = t;
  else if (commas > 0 && dots > 0) {
    // Both kinds: the last one is the decimal separator, the other must group thousands.
    const dec = t.lastIndexOf(",") > t.lastIndexOf(".") ? "," : ".";
    const group = dec === "," ? "." : ",";
    const [intPart, frac, extra] = t.split(dec);
    if (extra !== undefined || !frac || !/^\d+$/.test(frac)) return null;
    const int = grouped(intPart, group);
    normal = int === null ? null : `${int}.${frac}`;
  } else {
    const sep = commas > 0 ? "," : ".";
    const count = commas + dots;
    if (count > 1) normal = grouped(t, sep);
    else {
      const [intPart, frac] = t.split(sep);
      if (!intPart || !frac) return null;
      // One separator followed by exactly 3 digits after a 1 to 3 digit group not starting with 0
      // reads as thousands ("1,000"); otherwise it is the decimal separator ("0.250", "12,5").
      normal = /^[1-9]\d{0,2}$/.test(intPart) && /^\d{3}$/.test(frac) ? `${intPart}${frac}` : `${intPart}.${frac}`;
    }
  }
  if (normal === null || !/^\d+(\.\d+)?$/.test(normal)) return null;
  const n = Number(normal);
  return Number.isFinite(n) ? n : null;
}

