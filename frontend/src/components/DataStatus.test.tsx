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
  it("FR-16: warns about a stale source and shows its last successful update time", () => {
    withHealth(fixtures.health, <DataStatus relevant={PAIR_SOURCES.EURUSD} />);
    const warning = screen.getByTestId("stale-warning");
    const item = within(warning).getByText("Atlanta Fed Market Probability Tracker").closest("li")!;
    expect(item).toHaveTextContent("last successful update 16 Oct 2026, 15:20 UTC");
    expect(item).toHaveTextContent("(5 days ago)");
    expect(item).toHaveTextContent("Last run failed: Schema check failed");
    expect(within(item).getByTestId("stale-last-success")).toHaveAttribute("datetime", "2026-10-16T15:20:44Z");
  });

  it("FR-16: says 'never' for a source that never succeeded", () => {
    withHealth(fixtures.health, <DataStatus relevant={PAIR_SOURCES.USDAMD} />);
    const warning = screen.getByTestId("stale-warning");
    expect(warning).toHaveTextContent("Stale data from 2 sources");
    const item = within(warning).getByText("CBA decisions (cba.am, ARKA, Interfax)").closest("li")!;
    expect(within(item).getByTestId("stale-last-success")).toHaveTextContent("never");
  });

  it("shows the last update time of every relevant source", () => {
    const { container } = withHealth(fixtures.health, <DataStatus relevant={PAIR_SOURCES.EURUSD} />);
    const rows = [...container.querySelectorAll<HTMLLIElement>(".source-list li")];
    expect(rows.map((r) => r.dataset.source)).toEqual(PAIR_SOURCES.EURUSD);
    expect(rows[0]).toHaveTextContent("15:16");
    expect(rows.find((r) => r.dataset.source === "atlanta_fed")).toHaveTextContent("16 Oct 15:20stale");
  });

  it("shows no warning when every relevant source is fresh", () => {
    withHealth(fixtures.health, <DataStatus relevant={["frankfurter_ecb", "fred"]} />);
    expect(screen.queryByTestId("stale-warning")).toBeNull();
  });

  it("falls back to the forecast's stale_sources when health is unavailable", () => {
    withHealth(
      undefined,
      <DataStatus relevant={PAIR_SOURCES.USDAMD} extraStale={fixtures.latest.USDAMD.stale_sources} />,
      new Error("503: down"),
    );
    expect(screen.getByTestId("stale-warning")).toHaveTextContent("CBA decisions (cba.am, ARKA, Interfax) last successful update never");
    expect(screen.getByText(/Source status unavailable/)).toBeInTheDocument();
  });
});
