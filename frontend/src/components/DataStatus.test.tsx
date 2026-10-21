import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { HealthResponse } from "../api/types";
import { PAIR_SOURCES } from "../lib/constants";
import { HealthContext } from "../lib/health";
import type { ApiState } from "../lib/useApi";
import { fixtures } from "../mocks";
import { DataStatus } from "./DataStatus";

function withHealth(data: HealthResponse | undefined, ui: React.ReactNode, error?: Error) {
  const state: ApiState<HealthResponse> = { data, error, loading: false, refreshing: false, reload: () => {} };
  return render(<HealthContext.Provider value={state}>{ui}</HealthContext.Provider>);
}

describe("DataStatus", () => {
  it("FR-16: one compact warning names the stale source and its last successful update time", () => {
    withHealth(fixtures.health, <DataStatus relevant={PAIR_SOURCES.EURUSD} />);
    const warning = screen.getByTestId("stale-warning");
    expect(warning).toHaveTextContent("Atlanta Fed, last successful update 16 Oct 2026, 15:20 UTC (5 days ago)");
    expect(within(warning).getByTestId("stale-last-success")).toHaveAttribute("datetime", "2026-10-16T15:20:44Z");
  });

  it("FR-16: says 'never' for a source that never succeeded", () => {
    withHealth(fixtures.health, <DataStatus relevant={PAIR_SOURCES.USDAMD} />);
    const warning = screen.getByTestId("stale-warning");
    expect(warning).toHaveTextContent("CBA news, last successful update never");
    expect(screen.getByTestId("data-summary")).toHaveTextContent("2 of 6 sources stale");
  });

  it("collapses to one quiet line, with every source's last update in the details", () => {
    const { container } = withHealth(fixtures.health, <DataStatus relevant={PAIR_SOURCES.EURUSD} />);
    expect(screen.getByTestId("data-summary")).toHaveTextContent("Data updated 15:17 · 1 of 6 sources stale");
    const rows = [...container.querySelectorAll<HTMLLIElement>(".source-list li")];
    expect(rows.map((r) => r.dataset.source)).toEqual(PAIR_SOURCES.EURUSD);
    expect(rows[0]).toHaveTextContent("15:16");
    expect(container.querySelector(".source-dot")).toBeNull();
  });

  it("says all sources are current and shows no warning when nothing is stale", () => {
    withHealth(fixtures.health, <DataStatus relevant={["frankfurter_ecb", "fred"]} />);
    expect(screen.getByTestId("data-summary")).toHaveTextContent("all sources current");
    expect(screen.queryByTestId("stale-warning")).toBeNull();
  });

  it("falls back to the forecast's stale_sources when health is unavailable", () => {
    withHealth(
      undefined,
      <DataStatus relevant={PAIR_SOURCES.USDAMD} extraStale={fixtures.latest.USDAMD.stale_sources} />,
      new Error("503: down"),
    );
    expect(screen.getByTestId("stale-warning")).toHaveTextContent("CBA news, last successful update never");
    expect(screen.getByText(/Source status unavailable/)).toBeInTheDocument();
  });
});
