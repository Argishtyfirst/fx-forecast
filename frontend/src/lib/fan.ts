/**
 * Fan chart geometry, kept pure so it can be tested without a DOM.
 *
 * Time runs in trading days: history points sit at t = -(n-1) .. 0 (0 is the spot date) and the
 * horizons at t = 1, 5, 21. Each band starts with zero width at the spot and is interpolated
 * piecewise linearly between the horizon points.
 */
import type { BandKey, HorizonForecast, MeetingRef, RatePoint } from "../api/types";
import { BAND_KEYS } from "./constants";
import { daysBetween } from "./format";

export interface FanVertex {
  t: number;
  date: string;
  label: string | null; // "1D" | "1W" | "1M" (null for the spot vertex)
  center: number;
  bands: Record<BandKey, [number, number]>;
}

export function fanVertices(spot: number, spotDate: string, horizons: HorizonForecast[]): FanVertex[] {
  const start: FanVertex = {
    t: 0,
    date: spotDate,
    label: null,
    center: spot,
    bands: { "50": [spot, spot], "80": [spot, spot], "95": [spot, spot] },
  };
  const rest = [...horizons]
    .sort((a, b) => a.days - b.days)
    .map((h) => ({
      t: h.days,
      date: h.target_date,
      label: h.label,
      center: h.center,
      bands: Object.fromEntries(
        BAND_KEYS.map((k) => {
          const b = h.bands[k];
          return [k, b ? [Math.min(b[0], b[1]), Math.max(b[0], b[1])] : [h.center, h.center]];
        }),
      ) as Record<BandKey, [number, number]>,
    }));
  return [start, ...rest];
}

/** Closed polygon for one band: upper edge left to right, then lower edge right to left. */
export function bandPolygon(vertices: FanVertex[], key: BandKey): [number, number][] {
  const upper = vertices.map((v) => [v.t, v.bands[key][1]] as [number, number]);
  const lower = [...vertices].reverse().map((v) => [v.t, v.bands[key][0]] as [number, number]);
  return [...upper, ...lower];
}

/** Linear interpolation of a band edge at trading-day time t (0 <= t <= last horizon). */
export function bandAt(vertices: FanVertex[], key: BandKey, t: number): [number, number] | null {
  for (let i = 1; i < vertices.length; i += 1) {
    const a = vertices[i - 1];
    const b = vertices[i];
    if (t >= a.t && t <= b.t) {
      const w = b.t === a.t ? 0 : (t - a.t) / (b.t - a.t);
      return [
        a.bands[key][0] + (b.bands[key][0] - a.bands[key][0]) * w,
        a.bands[key][1] + (b.bands[key][1] - a.bands[key][1]) * w,
      ];
    }
  }
  return null;
}

/**
 * Trading-day time of a calendar date inside the forecast window, interpolated between the
 * known anchors (spot date and the horizon target dates). Null outside (spot, last target].
 */
export function dateToT(date: string, vertices: FanVertex[]): number | null {
  for (let i = 1; i < vertices.length; i += 1) {
    const a = vertices[i - 1];
    const b = vertices[i];
    if (date > a.date && date <= b.date) {
      const span = daysBetween(a.date, b.date);
      const w = span <= 0 ? 1 : daysBetween(a.date, date) / span;
      return a.t + (b.t - a.t) * w;
    }
  }
  return null;
}

export interface PlacedMeeting extends MeetingRef {
  t: number;
  horizons: string[]; // horizon labels whose window contains this meeting
}

/** Unique meetings across all horizons, placed on the trading-day axis. */
export function placeMeetings(horizons: HorizonForecast[], vertices: FanVertex[]): PlacedMeeting[] {
  const byKey = new Map<string, PlacedMeeting>();
  for (const h of [...horizons].sort((a, b) => a.days - b.days)) {
    for (const m of h.meetings) {
      const key = `${m.bank}:${m.date}`;
      const existing = byKey.get(key);
      if (existing) {
        existing.horizons.push(h.label);
        continue;
      }
      const t = dateToT(m.date, vertices);
      if (t === null) continue;
      byKey.set(key, { ...m, t, horizons: [h.label] });
    }
  }
  return [...byKey.values()].sort((a, b) => a.t - b.t || a.bank.localeCompare(b.bank));
}

/** The last `n` points up to and including the spot date. */
export function historyWindow(rates: RatePoint[], spotDate: string, n = 90): RatePoint[] {
  const upTo = rates.filter((r) => r.date <= spotDate).sort((a, b) => a.date.localeCompare(b.date));
  return upTo.slice(-n);
}

/** Greedy lane assignment so labels that would overlap move to the next row. */
export function assignLanes(xs: { x: number; width: number }[], gap = 4, maxLanes = 3): number[] {
  const laneEnds: number[] = [];
  return xs.map(({ x, width }) => {
    for (let lane = 0; lane < maxLanes; lane += 1) {
      if (laneEnds[lane] === undefined || x >= laneEnds[lane] + gap) {
        laneEnds[lane] = x + width;
        return lane;
      }
    }
    const lane = maxLanes - 1;
    laneEnds[lane] = x + width;
    return lane;
  });
}

export function yDomain(history: RatePoint[], vertices: FanVertex[], pad = 0.08): [number, number] {
  const values = [
    ...history.map((r) => r.rate),
    ...vertices.flatMap((v) => [v.bands["95"][0], v.bands["95"][1], v.center]),
  ];
  if (values.length === 0) return [0, 1];
  const lo = Math.min(...values);
  const hi = Math.max(...values);
  const span = hi - lo || Math.abs(hi) * 0.01 || 1;
  return [lo - span * pad, hi + span * pad];
}
