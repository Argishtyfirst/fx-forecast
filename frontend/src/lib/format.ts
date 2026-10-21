/** Number and date formatting. Rates keep their source precision; nothing is rounded into a promise. */

const MINUS = "−";

export function fmtRate(x: number | null | undefined, decimals: number): string {
  if (x === null || x === undefined || !Number.isFinite(x)) return "—";
  return x.toFixed(decimals).replace("-", MINUS);
}

export function fmtRange(lo: number, hi: number, decimals: number): string {
  return `${fmtRate(lo, decimals)} – ${fmtRate(hi, decimals)}`;
}

/** Signed number with a true minus sign, e.g. "+12.5", "−4", "0". */
export function fmtSigned(x: number | null | undefined, digits = 0): string {
  if (x === null || x === undefined || !Number.isFinite(x)) return "—";
  const r = Number(x.toFixed(digits));
  if (r === 0) return (0).toFixed(digits);
  return `${r > 0 ? "+" : MINUS}${Math.abs(r).toFixed(digits)}`;
}

export function fmtBps(x: number | null | undefined, signed = true): string {
  if (x === null || x === undefined || !Number.isFinite(x)) return "—";
  const digits = Number.isInteger(Math.round(x * 10) / 10) ? 0 : 1;
  return `${signed ? fmtSigned(x, digits) : x.toFixed(digits)} bps`;
}

export function fmtPct(x: number | null | undefined, digits = 1): string {
  if (x === null || x === undefined || !Number.isFinite(x)) return "—";
  return `${(x * 100).toFixed(digits)}%`;
}

/** A value that is already in percent (policy rates). */
export function fmtPercentValue(x: number | null | undefined, digits = 2): string {
  if (x === null || x === undefined || !Number.isFinite(x)) return "—";
  return `${x.toFixed(digits)}%`;
}

export function fmtNum(x: number | null | undefined, digits = 2): string {
  if (x === null || x === undefined || !Number.isFinite(x)) return "—";
  return x.toFixed(digits).replace("-", MINUS);
}

export function fmtInt(x: number | null | undefined): string {
  if (x === null || x === undefined || !Number.isFinite(x)) return "—";
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
  if (n === null || n === undefined) return "—";
  if (n === 0) return "today";
  if (n === 1) return "tomorrow";
  if (n < 0) return `${-n} days ago`;
  return `in ${n} days`;
}

export function titleCase(s: string): string {
  return s.replace(/_/g, " ").replace(/^\w/, (c) => c.toUpperCase());
}
