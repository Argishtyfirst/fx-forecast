import { describe, expect, it } from "vitest";
import { fixtures } from "../mocks";
import { assignLanes, bandAt, bandPolygon, dateToT, fanVertices, historyWindow, placeMeetings, yDomain } from "./fan";

const latest = fixtures.latest.EURUSD;
const vertices = fanVertices(latest.spot, latest.spot_date, latest.horizons);

describe("fan geometry", () => {
  it("FR-14: starts with zero width at the spot and has a vertex per horizon", () => {
    expect(vertices.map((v) => v.t)).toEqual([0, 1, 5, 21]);
    expect(vertices.map((v) => v.label)).toEqual([null, "1D", "1W", "1M"]);
    for (const k of ["50", "80", "95"] as const) {
      expect(vertices[0].bands[k]).toEqual([latest.spot, latest.spot]);
    }
  });

  it("FR-09: each band is nested inside the wider one at every horizon", () => {
    for (const v of vertices.slice(1)) {
      expect(v.bands["95"][0]).toBeLessThan(v.bands["80"][0]);
      expect(v.bands["80"][0]).toBeLessThan(v.bands["50"][0]);
      expect(v.bands["50"][1]).toBeLessThan(v.bands["80"][1]);
      expect(v.bands["80"][1]).toBeLessThan(v.bands["95"][1]);
    }
  });

  it("builds a closed polygon through the upper then lower edge of all 3 horizons", () => {
    const poly = bandPolygon(vertices, "80");
    expect(poly).toHaveLength(8);
    expect(poly.map(([t]) => t)).toEqual([0, 1, 5, 21, 21, 5, 1, 0]);
    const h1m = latest.horizons.find((h) => h.label === "1M")!;
    expect(poly[3]).toEqual([21, h1m.bands["80"][1]]);
    expect(poly[4]).toEqual([21, h1m.bands["80"][0]]);
  });

  it("interpolates band edges linearly in trading-day time", () => {
    const h1w = vertices[2];
    const h1m = vertices[3];
    const mid = bandAt(vertices, "95", 13)!;
    expect(mid[1]).toBeCloseTo((h1w.bands["95"][1] + h1m.bands["95"][1]) / 2, 10);
    expect(bandAt(vertices, "95", 0)).toEqual([latest.spot, latest.spot]);
    expect(bandAt(vertices, "95", 30)).toBeNull();
  });

  it("FR-12: places meetings inside the horizons on the trading-day axis", () => {
    // 28 Oct is the 1W target date; 29 Oct falls one calendar day later in the 1W..1M segment.
    expect(dateToT("2026-10-28", vertices)).toBe(5);
    const t29 = dateToT("2026-10-29", vertices)!;
    expect(t29).toBeGreaterThan(5);
    expect(t29).toBeLessThan(6);
    expect(dateToT("2026-10-21", vertices)).toBeNull();
    expect(dateToT("2026-12-09", vertices)).toBeNull();

    const meetings = placeMeetings(latest.horizons, vertices);
    expect(meetings.map((m) => `${m.bank} ${m.date}`)).toEqual(["FED 2026-10-28", "ECB 2026-10-29"]);
    expect(meetings[0].horizons).toEqual(["1W", "1M"]);
    expect(meetings[1].horizons).toEqual(["1M"]);
  });

  it("FR-14: keeps exactly 90 trading days of history ending at the spot date", () => {
    const hist = historyWindow(fixtures.rates.EURUSD.rates, latest.spot_date, 90);
    expect(hist).toHaveLength(90);
    expect(hist[hist.length - 1].date).toBe(latest.spot_date);
    expect(hist[hist.length - 1].rate).toBe(latest.spot);
  });

  it("covers history and the 95% band in the y domain", () => {
    const hist = historyWindow(fixtures.rates.EURUSD.rates, latest.spot_date, 90);
    const [lo, hi] = yDomain(hist, vertices);
    expect(lo).toBeLessThan(Math.min(...vertices.map((v) => v.bands["95"][0])));
    expect(hi).toBeGreaterThan(Math.max(...vertices.map((v) => v.bands["95"][1])));
  });

  it("moves overlapping labels to the next lane", () => {
    expect(assignLanes([{ x: 0, width: 30 }, { x: 10, width: 30 }, { x: 80, width: 30 }])).toEqual([0, 1, 0]);
  });
});
