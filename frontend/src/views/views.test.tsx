import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { App } from "../App";
import { DISCLAIMER } from "../lib/constants";
import { fixtures } from "../mocks";
import { mockFetch, useFixedClock } from "../test/utils";

function renderAt(hash: string) {
  window.history.replaceState(null, "", `/${hash}`);
  return render(<App />);
}

beforeEach(() => {
  useFixedClock();
  try {
    window.localStorage.clear();
  } catch {
    // ignore
  }
});
afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe("Pair view", () => {
  it("FR-14 / FR-12: renders the decision hero, the fan chart and the ranges table from the mocks", async () => {
    mockFetch();
    renderAt("#/pair/EURUSD");
    await screen.findByTestId("fan-chart");
    expect(screen.getByRole("heading", { level: 1, name: "Sell EUR for USD now?" })).toBeInTheDocument();
    expect(screen.getByTestId("verdict")).toHaveTextContent("Wait");
    const row1w = screen.getByTestId("range-row-1W");
    expect(within(row1w).getByTestId("range-80")).toHaveTextContent("1.1071 to 1.1344");
    expect(within(row1w).getByTestId("range-meetings")).toHaveTextContent("Fed 28 Oct");
    expect(within(screen.getByTestId("range-row-1M")).getByTestId("range-meetings")).toHaveTextContent("Fed 28 Oct, ECB 29 Oct");
    expect(within(screen.getByTestId("range-row-1D")).getByTestId("range-meetings")).toHaveTextContent("None");
  });

  it("shows the disclaimer on the decision, the chart and the ranges", async () => {
    mockFetch();
    renderAt("#/pair/EURUSD");
    await screen.findByTestId("fan-chart");
    for (const id of ["decision-hero", "ranges"]) {
      expect(within(screen.getByTestId(id)).getByTestId("disclaimer")).toHaveTextContent(DISCLAIMER);
    }
    const chartCard = screen.getByTestId("fan-chart").closest("section")!;
    expect(within(chartCard).getByTestId("disclaimer")).toHaveTextContent(DISCLAIMER);
  });

  it("FR-16: shows the stale warning with the last successful update", async () => {
    mockFetch();
    renderAt("#/pair/USDAMD");
    const warning = await screen.findByTestId("stale-warning");
    expect(warning).toHaveTextContent("Atlanta Fed, last successful update 16 Oct 2026, 15:20 UTC");
    expect(warning).toHaveTextContent("CBA news, last successful update never");
  });

  it("the horizon switch changes the verdict and the chart emphasis, and is remembered", async () => {
    mockFetch();
    renderAt("#/pair/EURAMD");
    await screen.findByTestId("fan-chart");
    expect(screen.getByTestId("verdict")).toHaveTextContent(/^Wait$/);
    expect(screen.getByTestId("verdict-sentence")).toHaveTextContent("58% chance the rate is higher by 19 Nov.");
    const selectedPoint = () =>
      screen.getAllByTestId("ai-point").find((p) => p.getAttribute("data-selected") === "true")!.getAttribute("data-horizon");
    expect(selectedPoint()).toBe("1M");
    await userEvent.click(screen.getByRole("button", { name: "tomorrow" }));
    expect(screen.getByTestId("verdict")).toHaveTextContent(/^Sell now$/);
    expect(screen.getByTestId("verdict-sentence")).toHaveTextContent("56% chance the rate is lower by 22 Oct.");
    expect(selectedPoint()).toBe("1D");
    expect(screen.getByTestId("ai-label")).toHaveTextContent("AI: 404.75 by 22 Oct (Sell now)");
    expect(window.localStorage.getItem("fxf-horizon")).toBe("1D");
    await userEvent.click(screen.getByRole("button", { name: "within a week" }));
    expect(screen.getByTestId("verdict")).toHaveTextContent(/^No clear answer$/);
    expect(screen.getByTestId("verdict-sentence")).toHaveTextContent("Close to even: 52% chance the rate is higher by 28 Oct.");
  });

  it("uses no en or em dashes in visible text on any view", async () => {
    for (const hash of ["#/pair/EURAMD", "#/drivers/EURAMD/1M", "#/events/EURAMD", "#/backtest/EURAMD"]) {
      mockFetch();
      const { unmount } = renderAt(hash);
      await screen.findByRole("heading", { level: 1 });
      await waitFor(() => expect(document.body.textContent).not.toMatch(/Loading/));
      expect(document.body.textContent).not.toMatch(/[\u2013\u2014]/);
      unmount();
    }
  });

  it("requests 90+ days of rates ending at the spot date", async () => {
    const calls = mockFetch();
    renderAt("#/pair/EURUSD");
    await screen.findByTestId("fan-chart");
    expect(calls).toContain("/api/forecasts/EURUSD/latest");
    expect(calls.find((c) => c.startsWith("/api/rates/EURUSD"))).toBe("/api/rates/EURUSD?from=2026-04-04&to=2026-10-21");
    expect(screen.getByTestId("history-line")).toHaveAttribute("data-points", "90");
  });

  it("treats a 404 'no forecast yet' as an empty state, not a crash", async () => {
    mockFetch({ "/api/forecasts/EURUSD/latest": { status: 404, body: { detail: "No forecast yet" } } });
    renderAt("#/pair/EURUSD");
    expect(await screen.findByText("No forecast yet")).toBeInTheDocument();
    expect(screen.getByTestId("history-line")).toBeInTheDocument();
    expect(screen.queryByTestId("ranges")).toBeNull();
  });

  it("shows an error state with a retry when the API fails", async () => {
    mockFetch({ "/api/forecasts/EURUSD/latest": { status: 500, body: { detail: "Internal Server Error" } } });
    renderAt("#/pair/EURUSD");
    expect(await screen.findByText("Could not load the forecast")).toBeInTheDocument();
    expect(screen.getByText("500: Internal Server Error")).toBeInTheDocument();
    mockFetch();
    await userEvent.click(screen.getByRole("button", { name: /Retry/ }));
    expect(await screen.findByTestId("fan-chart")).toBeInTheDocument();
  });
});

describe("EUR/AMD", () => {
  it("renders the third pair with all three banks", async () => {
    mockFetch();
    renderAt("#/pair/EURAMD");
    await screen.findByTestId("fan-chart");
    expect(screen.getByRole("heading", { level: 1, name: "Sell EUR for AMD now?" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 2, name: /EUR\/AMD/ })).toHaveTextContent("spot 405.04 on 21 Oct");
    expect(screen.getByTestId("ai-tag")).toHaveTextContent("Gemini AI view, not yet proven (0 of 250 checked)");
    expect(screen.getByTestId("ai-path")).toHaveAttribute("data-points", "4");
    expect(screen.getByTestId("fact-stat")).toHaveTextContent("No proven edge");
    expect(screen.getByTestId("fact-interest")).toHaveTextContent("AMD pays 4.50%/yr more than EUR");
    expect(screen.getAllByTestId("meeting-marker").map((m) => m.dataset.bank)).toEqual(["FED", "ECB"]);
    expect(screen.getByRole("link", { name: "EUR/AMD" })).toHaveAttribute("aria-current", "page");
  });

  it("shows the CBA minus ECB differential and a card per bank", async () => {
    mockFetch();
    renderAt("#/drivers/EURAMD/1M");
    expect(await screen.findByTestId("rate-diff")).toHaveTextContent("+450 bps");
    expect(screen.getByText(/CBA minus ECB/)).toBeInTheDocument();
    for (const b of ["FED", "ECB", "CBA"]) expect(screen.getByTestId(`bank-card-${b}`)).toBeInTheDocument();
  });
});

describe("Drivers view", () => {
  it("FR-11 / FR-15: shows the served model, differential, forward rate, volatility and bank scores", async () => {
    mockFetch();
    renderAt("#/drivers/EURUSD/1M");
    expect(await screen.findByTestId("rate-diff")).toHaveTextContent("+137.5 bps");
    expect(screen.getByText(/Diebold-Mariano p = 0.14 misses the 0.10 bar/)).toBeInTheDocument();
    expect(screen.getByTestId("forward-rate")).toHaveTextContent("1.12198");
    expect(screen.getByTestId("garch-vol")).toHaveTextContent("6.8%");
    expect(screen.getByTestId("event-widening")).toHaveTextContent("Widened");
    const fed = screen.getByTestId("bank-card-FED");
    expect(fed).toHaveTextContent("−4 bps");
    expect(fed).toHaveTextContent("in 7 days");
    expect(within(fed).getByRole("img", { name: /Hawkish score \u22120\.35, leaning dovish/ })).toBeInTheDocument();
    expect(within(screen.getByTestId("bank-card-ECB")).getByText("Neutral")).toBeInTheDocument();
    expect(await screen.findByText("All candidates on this run")).toBeInTheDocument();
    expect(screen.getAllByTestId("disclaimer").length).toBeGreaterThan(0);
  });

  it("switches horizon: 1D has no event widening", async () => {
    mockFetch();
    renderAt("#/drivers/EURUSD/1M");
    await screen.findByTestId("rate-diff");
    const group = screen.getByRole("group", { name: "Horizon" });
    await userEvent.click(within(group).getByRole("button", { name: "1D" }));
    expect(screen.getByTestId("event-widening")).toHaveTextContent("None");
    expect(window.location.hash).toBe("#/drivers/EURUSD/1D");
  });
});

describe("Events view", () => {
  it("FR-05 / FR-06 / FR-07: lists decisions with surprise, score, scorer and an expandable diff", async () => {
    mockFetch();
    renderAt("#/events/EURUSD");
    const list = await screen.findByTestId("decision-list");
    const items = within(list).getAllByTestId("decision");
    expect(items).toHaveLength(6);
    const cba = items[0];
    expect(cba).toHaveTextContent("Tue, 6 Oct 2026");
    expect(cba).toHaveTextContent("6.750% → 6.500%");
    expect(cba).toHaveTextContent("−25 bps");
    expect(cba).toHaveTextContent("scorer claude-haiku-5-5@p1");
    expect(cba).toHaveTextContent("Lombard repo 8.25% → 8.00%");
    await userEvent.click(within(cba).getByRole("button", { name: /Statement changes/ }));
    const diff = within(cba).getByTestId("statement-diff");
    expect(diff.querySelectorAll(".diff-added")).toHaveLength(3);
    expect(diff.querySelectorAll(".diff-removed")).toHaveLength(2);
    expect(within(cba).getByRole("link", { name: /Full statement/ })).toHaveAttribute("href", "https://www.cba.am/en/press-center/press-releases");
    expect(within(screen.getByTestId("upcoming-list")).getAllByRole("listitem")[0]).toHaveTextContent("in 7 days");
  });

  it("filters by bank", async () => {
    mockFetch();
    renderAt("#/events/EURUSD");
    await screen.findByTestId("decision-list");
    await userEvent.click(screen.getByRole("button", { name: "ECB" }));
    const items = within(screen.getByTestId("decision-list")).getAllByTestId("decision");
    expect(items.map((i) => i.dataset.bank)).toEqual(["ECB", "ECB"]);
    expect(window.location.hash).toBe("#/events/EURUSD/ECB");
  });
});

describe("Backtest view", () => {
  it("FR-13: shows metrics per horizon and model against the targets, with the served model marked", async () => {
    mockFetch();
    renderAt("#/backtest/EURUSD");
    const m1 = await screen.findByTestId("backtest-1M");
    const lgbm = m1.querySelector<HTMLTableRowElement>('tr[data-model="lightgbm"]')!;
    // Lower MAE than the random walk, but DM p = 0.14 misses 0.10: not promoted, not served.
    expect(lgbm).toHaveTextContent("0.962");
    expect(within(lgbm).queryByText("Promoted")).toBeNull();
    const dm = [...lgbm.querySelectorAll("td")].find((td) => td.textContent?.includes("0.14"))!;
    expect(dm).toHaveAttribute("data-verdict", "fail");
    const rw = m1.querySelector<HTMLTableRowElement>('tr[data-model="random_walk"]')!;
    expect(within(rw).getByText("Served")).toBeInTheDocument();
    expect(within(rw).getByText("Baseline")).toBeInTheDocument();
    // 74.4% is outside 75-85%: a fail, marked with an icon, not color alone.
    const cov80 = [...rw.querySelectorAll("td")].find((td) => td.textContent?.includes("74.4%"))!;
    expect(cov80).toHaveAttribute("data-verdict", "fail");
    expect(within(cov80).getByTitle("misses target")).toBeInTheDocument();
    expect(screen.getByTestId("backtest-1D")).toBeInTheDocument();
    expect(screen.getByTestId("backtest-1W")).toBeInTheDocument();
  });

  it("marks a promoted, served model", async () => {
    const bt = structuredClone(fixtures.backtests.EURUSD);
    for (const m of bt.metrics) {
      if (m.horizon_days !== 21) continue;
      m.served = m.model === "lightgbm";
      if (m.model === "lightgbm" && m.window === "250d") {
        m.dm_pvalue = 0.07;
        m.promoted = true;
      }
    }
    bt.metrics = bt.metrics.filter((m) => m.horizon_days === 21);
    mockFetch({ "/api/backtests/EURUSD?horizon=21": { status: 200, body: bt } });
    renderAt("#/backtest/EURUSD");
    const m1 = await screen.findByTestId("backtest-1M");
    const lgbm = m1.querySelector<HTMLTableRowElement>('tr[data-model="lightgbm"]')!;
    expect(within(lgbm).getByText("Served")).toBeInTheDocument();
    expect(within(lgbm).getByText("Promoted")).toBeInTheDocument();
    expect(lgbm).toHaveTextContent("below 0.98");
  });

  it("toggles the window to the full history", async () => {
    mockFetch();
    renderAt("#/backtest/EURUSD");
    await screen.findByTestId("backtest-1M");
    await userEvent.click(screen.getByRole("button", { name: "Full history" }));
    await waitFor(() => expect(window.location.hash).toBe("#/backtest/EURUSD/full"));
    const m1 = screen.getByTestId("backtest-1M");
    expect(m1).toHaveTextContent("2,948");
    expect(within(m1).queryByText("Promoted")).toBeNull();
  });
});

describe("Shell", () => {
  it("credits the data sources (NFR-08)", async () => {
    mockFetch();
    renderAt("#/pair/EURUSD");
    await screen.findByTestId("fan-chart");
    for (const name of [/European Central Bank/, /Central Bank of Armenia/, /FRED, Federal Reserve Bank of St. Louis/, /^Frankfurter$/]) {
      expect(screen.getByRole("link", { name })).toBeInTheDocument();
    }
  });

  it("toggles dark mode and remembers it", async () => {
    mockFetch();
    renderAt("#/pair/EURUSD");
    await userEvent.click(screen.getByTestId("theme-toggle"));
    expect(document.documentElement.dataset.theme).toBe("dark");
    expect(window.localStorage.getItem("fxf-theme")).toBe("dark");
  });

  it("switches pair through the URL", async () => {
    mockFetch();
    renderAt("#/pair/EURUSD");
    await screen.findByTestId("fan-chart");
    await userEvent.click(screen.getByRole("link", { name: "USD/AMD" }));
    expect(window.location.hash).toBe("#/pair/USDAMD");
    expect(await screen.findByRole("heading", { level: 1, name: "Sell USD for AMD now?" })).toBeInTheDocument();
    expect(await screen.findByRole("heading", { level: 2, name: /USD\/AMD/ })).toHaveTextContent("spot 361.42");
  });
});
