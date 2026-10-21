import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { PairId } from "../api/types";
import { PAIRS } from "../lib/constants";
import { historyWindow } from "../lib/fan";
import { fixtures } from "../mocks";
import { FanChart } from "./FanChart";

function renderChart(pair: PairId = "EURUSD", width = 900) {
  const forecast = fixtures.latest[pair];
  const history = historyWindow(fixtures.rates[pair].rates, forecast.spot_date, 90);
  return render(
    <FanChart pairLabel={PAIRS[pair].label} decimals={PAIRS[pair].decimals} history={history} forecast={forecast} width={width} />,
  );
}

describe("FanChart", () => {
  it("FR-14: renders the 95/80/50 band paths spanning all 3 horizons", () => {
    const { container } = renderChart();
    const bands = [...container.querySelectorAll<SVGPathElement>("path[data-band]")];
    expect(bands.map((b) => b.dataset.band)).toEqual(["95", "80", "50"]);
    for (const b of bands) {
      expect(b.dataset.horizons).toBe("1D 1W 1M");
      // 8 vertices: spot, 1D, 1W, 1M along the top and back along the bottom.
      expect(b.getAttribute("d")!.match(/[ML]/g)).toHaveLength(8);
      expect(b.getAttribute("d")).toMatch(/Z$/);
    }
    const points = [...container.querySelectorAll<SVGCircleElement>("[data-horizon-point]")];
    expect(points.map((p) => p.dataset.horizonPoint)).toEqual(["1D", "1W", "1M"]);
  });

  it("FR-14: draws 90 trading days of history and a subtle center line", () => {
    renderChart();
    expect(screen.getByTestId("history-line")).toHaveAttribute("data-points", "90");
    expect(screen.getByTestId("center-line")).toBeInTheDocument();
  });

  it("FR-12: marks each meeting inside the horizons with a tick and the bank label", () => {
    const { container } = renderChart();
    const markers = screen.getAllByTestId("meeting-marker");
    expect(markers.map((m) => `${m.dataset.bank} ${m.dataset.date}`)).toEqual(["FED 2026-10-28", "ECB 2026-10-29"]);
    expect(container.querySelectorAll(".fan-meeting-tick")).toHaveLength(2);
    expect(markers[0]).toHaveTextContent("Fed 28 Oct");
    expect(markers[1]).toHaveTextContent("ECB 29 Oct");
  });

  it("only marks the pair's own meetings (USD/AMD: Fed, no ECB)", () => {
    renderChart("USDAMD");
    const markers = screen.getAllByTestId("meeting-marker");
    expect(markers.map((m) => m.dataset.bank)).toEqual(["FED"]);
  });

  it("EUR/AMD marks Fed and ECB meetings inside the horizons; the CBA meets after 1M", () => {
    const { container } = renderChart("EURAMD");
    expect(screen.getAllByTestId("meeting-marker").map((m) => m.dataset.bank)).toEqual(["FED", "ECB"]);
    expect(container.querySelectorAll("path[data-band]")).toHaveLength(3);
  });

  it("is an accessible image with a text summary of the ranges", () => {
    renderChart();
    const svg = screen.getByRole("img", { name: /EUR\/USD fan chart/ });
    const label = svg.getAttribute("aria-label")!;
    expect(label).toContain("90 trading days of history");
    expect(label).toContain("80% ranges: 1D to 22 Oct 2026: 1.1151 – 1.1264");
    expect(label).toContain("Fed 28 Oct 2026, ECB 29 Oct 2026");
    expect(label).toContain("Statistical estimate. Not financial advice.");
  });

  it("renders history alone when there is no forecast yet", () => {
    const history = historyWindow(fixtures.rates.EURUSD.rates, "2026-10-21", 90);
    const { container } = render(<FanChart pairLabel="EUR/USD" decimals={4} history={history} forecast={null} width={600} />);
    expect(container.querySelectorAll("path[data-band]")).toHaveLength(0);
    expect(screen.getByTestId("history-line")).toHaveAttribute("data-points", "90");
  });

  it("keeps horizon labels readable on a 380px screen", () => {
    const { container } = renderChart("EURUSD", 314);
    const labels = [...container.querySelectorAll(".fan-xaxis text")].map((t) => t.textContent);
    expect(labels).toEqual(expect.arrayContaining(["1D", "1W", "1M"]));
  });
});
