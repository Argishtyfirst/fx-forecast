/**
 * Number and date formatting. Rates keep their source precision; nothing is rounded into a promise.
 * Visible text uses no en or em dashes: ranges read "a to b" and missing values read "n/a".
 */

export const NA = "n/a";

const MINUS = "−";

export function fmtRate(x: number | null | undefined, decimals: number): string {
  if (x === null || x === undefined || !Number.isFinite(x)) return NA;
  return x.toFixed(decimals).replace("-", MINUS);
}

export function fmtRange(lo: number, hi: number, decimals: number): string {
  return `${fmtRate(lo, decimals)} to ${fmtRate(hi, decimals)}`;
}

/** Signed number with a true minus sign, e.g. "+12.5", "−4", "0". */
export function fmtSigned(x: number | null | undefined, digits = 0): string {
  if (x === null || x === undefined || !Number.isFinite(x)) return NA;
  const r = Number(x.toFixed(digits));
  if (r === 0) return (0).toFixed(digits);
  return `${r > 0 ? "+" : MINUS}${Math.abs(r).toFixed(digits)}`;
}

export function fmtBps(x: number | null | undefined, signed = true): string {
  if (x === null || x === undefined || !Number.isFinite(x)) return NA;
  const digits = Number.isInteger(Math.round(x * 10) / 10) ? 0 : 1;
  return `${signed ? fmtSigned(x, digits) : x.toFixed(digits)} bps`;
}

export function fmtPct(x: number | null | undefined, digits = 1): string {
  if (x === null || x === undefined || !Number.isFinite(x)) return NA;
  return `${(x * 100).toFixed(digits)}%`;
}

/** A value that is already in percent (policy rates). */
export function fmtPercentValue(x: number | null | undefined, digits = 2): string {
  if (x === null || x === undefined || !Number.isFinite(x)) return NA;
  return `${x.toFixed(digits)}%`;
}

export function fmtNum(x: number | null | undefined, digits = 2): string {
  if (x === null || x === undefined || !Number.isFinite(x)) return NA;
  return x.toFixed(digits).replace("-", MINUS);
}

export function fmtInt(x: number | null | undefined): string {
  if (x === null || x === undefined || !Number.isFinite(x)) return NA;
  return new Intl.NumberFormat("en-GB").format(x);
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

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const WEEKDAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];

/** "21 Oct 2026" */
export function fmtDate(iso: string): string {
  const d = parseDate(iso);
  return `${d.getUTCDate()} ${MONTHS[d.getUTCMonth()]} ${d.getUTCFullYear()}`;
}
/** "21 Oct" */
export function fmtShortDate(iso: string): string {
  const d = parseDate(iso);
  return `${d.getUTCDate()} ${MONTHS[d.getUTCMonth()]}`;
}
/** "Wed, 21 Oct 2026" */
export function fmtWeekdayDate(iso: string): string {
  return `${WEEKDAYS[parseDate(iso).getUTCDay()]}, ${fmtDate(iso)}`;
}
/** "Oct" */
export function fmtMonth(iso: string): string {
  return MONTHS[parseDate(iso).getUTCMonth()];
}

function localParts(d: Date) {
  const time = new Intl.DateTimeFormat("en-GB", {
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
    timeZoneName: "short",
  }).formatToParts(d);
  const get = (t: string) => time.find((p) => p.type === t)?.value ?? "";
  return {
    day: d.getDate(),
    month: MONTHS[d.getMonth()],
    year: d.getFullYear(),
    hm: `${get("hour")}:${get("minute")}`,
    tz: get("timeZoneName"),
  };
}

/** A UTC timestamp in the viewer's local time: "16 Oct 2026, 17:20 CEST". */
export function fmtDateTime(iso: string | null | undefined): string {
  if (!iso) return "never";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  const p = localParts(d);
  return `${p.day} ${p.month} ${p.year}, ${p.hm}${p.tz ? ` ${p.tz}` : ""}`;
}

/** Compact local time for status rows: "17:16" today, "16 Oct 17:20" otherwise. */
export function fmtCompactTime(iso: string | null | undefined, now: Date): string {
  if (!iso) return "never";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  const p = localParts(d);
  const sameDay = d.toDateString() === now.toDateString();
  return sameDay ? p.hm : `${p.day} ${p.month} ${p.hm}`;
}

/** "5 days ago", "3 hours ago", relative to `now` (the health check time, so tests are stable). */
export function fmtAgo(iso: string | null | undefined, now: Date): string {
  if (!iso) return "never";
  const ms = now.getTime() - new Date(iso).getTime();
  if (!Number.isFinite(ms)) return "";
  const min = Math.round(ms / 60_000);
  if (min < 1) return "just now";
  if (min < 60) return `${min} min ago`;
  const h = Math.round(min / 60);
  if (h < 48) return `${h} hour${h === 1 ? "" : "s"} ago`;
  const d = Math.round(h / 24);
  return `${d} days ago`;
}

export function fmtDaysUntil(n: number | null | undefined): string {
  if (n === null || n === undefined) return NA;
  if (n === 0) return "today";
  if (n === 1) return "tomorrow";
  if (n < 0) return `${-n} days ago`;
  return `in ${n} days`;
}

export function titleCase(s: string): string {
  return s.replace(/_/g, " ").replace(/^\w/, (c) => c.toUpperCase());
}

const THIN = " "; // narrow no-break space for digit grouping

/** Money with thin digit grouping: AMD without decimals ("425 300 AMD"), others with 2. */
export function fmtMoney(value: number | null | undefined, currency: string): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return NA;
  const digits = currency === "AMD" ? 0 : 2;
  const fixed = Math.abs(value).toFixed(digits);
  const [int, dec] = fixed.split(".");
  const grouped = int.replace(/\B(?=(\d{3})+(?!\d))/g, THIN);
  return `${value < 0 ? "−" : ""}${grouped}${dec ? `.${dec}` : ""} ${currency}`;
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

/** "Fri 17 Oct" */
export function fmtDayShort(iso: string): string {
  return fmtWeekdayDate(iso).replace(",", "").replace(/ \d{4}$/, "");
}
