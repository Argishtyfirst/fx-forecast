import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { DISCLAIMER } from "../lib/constants";
import { fixtures } from "../mocks";
import { AI_VIEWS, latestWith, SIGNALS } from "../mocks/signals";
import { SignalPanel } from "./SignalPanel";

function renderPanel(patch: Parameters<typeof latestWith>[0] = {}) {
  const latest = latestWith(patch);
  return render(<SignalPanel horizons={latest.horizons} decimals={2} disclaimer={latest.disclaimer} />);
}
const row = (label: string) => screen.getByTestId(`signal-${label}`);
const defaultSignal = (label: string) => fixtures.latest.EURAMD.horizons.find((h) => h.label === label)!.signal!;

describe("SignalPanel (FR-17): statistical answer", () => {
  it("asks the question with the base currency and has one answer per horizon", () => {
    renderPanel();
    const panel = screen.getByTestId("signal-panel");
    expect(within(panel).getByRole("heading", { name: "Sell EUR now?" })).toBeInTheDocument();
    expect(panel).toHaveTextContent("For converting EUR into AMD");
    expect(["1D", "1W", "1M"].map((l) => row(l).dataset.action)).toEqual(["no_edge", "no_edge", "no_edge"]);
  });

  it("no edge: leads with the risk of waiting and the interest line; the 50% is secondary", () => {
    renderPanel();
    const r = row("1M");
    const s = defaultSignal("1M");
    expect(within(r).getByTestId("signal-verdict")).toHaveTextContent(/^No clear edge$/);
    expect(within(r).getByTestId("signal-lead")).toHaveTextContent("Waiting 1M doesn’t improve your expected rate");
    expect(within(r).getByTestId("signal-risk")).toHaveTextContent(
      `Risk of waiting±2.6% (80% range ${s.downside_p10_rate.toFixed(2)} – ${s.upside_p90_rate.toFixed(2)} AMD per €)`,
    );
    const interest = within(r).getByTestId("signal-interest");
    expect(interest).toHaveTextContent("Holding AMD pays ~4.50%/yr more than EUR (~1.52 AMD per € over 1M)");
    expect(interest).toHaveTextContent("at policy rates; your bank’s rates differ");

    const prob = within(r).getByTestId("signal-prob");
    expect(prob).toHaveTextContent("50% chance of a better rate if you wait 1M");
    expect(prob).toHaveClass("signal-prob-secondary");
    // The lead comes before the probability in reading order.
    const lead = within(r).getByTestId("signal-lead");
    expect(lead.compareDocumentPosition(prob) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(within(r).getByTestId("confidence-scale")).toHaveAttribute("data-level", "none");
  });

  it("names the currency that pays more when the carry is negative", () => {
    renderPanel({ "1M": { signal: SIGNALS.negativeCarry } });
    expect(within(row("1M")).getByTestId("signal-interest")).toHaveTextContent(
      "Holding EUR pays ~4.50%/yr more than AMD (~1.52 AMD per € over 1M)",
    );
  });

  it("drops the interest line when the carry is unknown", () => {
    renderPanel({ "1M": { signal: SIGNALS.nullCarry } });
    expect(within(row("1M")).queryByTestId("signal-interest")).toBeNull();
    expect(within(row("1M")).getByTestId("signal-risk")).toBeInTheDocument();
  });

  it.each([
    ["wait", SIGNALS.waitMedium, "Wait", "58%"],
    ["sell_now", SIGNALS.sellNowHigh, "Yes, sell now", "31%"],
  ])("%s: leads with the verdict and its probability", (_name, signal, verdict, pct) => {
    renderPanel({ "1M": { signal } });
    const r = row("1M");
    expect(within(r).getByTestId("signal-verdict")).toHaveTextContent(new RegExp(`^${verdict}$`));
    expect(within(r).queryByTestId("signal-lead")).toBeNull();
    const prob = within(r).getByTestId("signal-prob");
    expect(prob).toHaveTextContent(`${pct} chance of a better rate if you wait 1M`);
    expect(prob).not.toHaveClass("signal-prob-secondary");
    expect(r).toHaveTextContent(signal.summary);
    expect(within(r).getByTestId("signal-risk")).toBeInTheDocument();
  });

  it("keeps the no-edge summary sentence in the evidence", async () => {
    renderPanel();
    const r = row("1W");
    await userEvent.click(within(r).getByText("Evidence behind the verdict"));
    expect(r.querySelector("details")).toHaveTextContent(defaultSignal("1W").summary);
    expect(within(r).getByTestId("signal-downside")).toHaveTextContent(`≤ ${defaultSignal("1W").downside_p10_rate.toFixed(2)}`);
    expect(within(r).getByTestId("signal-upside")).toHaveTextContent(`≥ ${defaultSignal("1W").upside_p90_rate.toFixed(2)}`);
  });

  it.each([
    ["none", SIGNALS.noEdgeNone],
    ["low", SIGNALS.waitLow],
    ["medium", SIGNALS.waitMedium],
    ["high", SIGNALS.sellNowHigh],
  ])("shows confidence %s on a labelled scale", (level, signal) => {
    renderPanel({ "1M": { signal } });
    const scale = within(row("1M")).getByTestId("confidence-scale");
    expect(scale).toHaveAttribute("data-level", level);
    expect(scale).toHaveAccessibleName("Confidence");
    expect(within(scale).getAllByRole("listitem").map((li) => li.textContent)).toEqual(["none", "low", "medium", "high"]);
    expect(within(scale).getByText(level)).toHaveAttribute("aria-current", "true");
  });

  it("shows the evidence behind a lean on expand", async () => {
    renderPanel({ "1M": { signal: SIGNALS.sellNowHigh } });
    const r = row("1M");
    await userEvent.click(within(r).getByText("Evidence behind the verdict"));
    const evidence = r.querySelector("details")!;
    expect(evidence).toHaveAttribute("open");
    expect(evidence).toHaveTextContent("Beats random walkYes");
    expect(evidence).toHaveTextContent("Direction hit rate61.0%");
    expect(evidence).toHaveTextContent("Diebold-Mariano p0.02");
    expect(evidence).toHaveTextContent("Backtest forecasts250");
  });

  it("carries the disclaimer", () => {
    renderPanel();
    expect(within(screen.getByTestId("signal-panel")).getByTestId("disclaimer")).toHaveTextContent(DISCLAIMER);
  });

  it("hides a horizon without a signal, and the whole panel when none has one", () => {
    const { unmount } = renderPanel({ "1D": { signal: null } });
    expect(screen.queryByTestId("signal-1D")).toBeNull();
    expect(row("1W")).toBeInTheDocument();
    unmount();
    const { container } = renderPanel({ "1D": { signal: null }, "1W": { signal: null }, "1M": { signal: null } });
    expect(container).toBeEmptyDOMElement();
  });

  it("also hides cleanly when the API omits the field", () => {
    const latest = latestWith({});
    for (const h of latest.horizons) delete h.signal;
    const { container } = render(<SignalPanel horizons={latest.horizons} decimals={2} disclaimer={latest.disclaimer} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("offers one horizon at a time on small screens (1M first) through a horizon switch", async () => {
    renderPanel();
    const tabs = screen.getByRole("group", { name: "Signal horizon" });
    expect(within(tabs).getByRole("button", { name: "1M" })).toHaveAttribute("aria-pressed", "true");
    expect(row("1M")).toHaveClass("is-active");
    expect(row("1D")).not.toHaveClass("is-active");
    await userEvent.click(within(tabs).getByRole("button", { name: "1D" }));
    expect(row("1D")).toHaveClass("is-active");
    expect(row("1M")).not.toHaveClass("is-active");
  });
});

describe("SignalPanel: AI view (experimental)", () => {
  it("is labelled experimental, with its chance, confidence, reasoning, model and time", () => {
    renderPanel();
    const ai = within(row("1M")).getByTestId("ai-view");
    const v = fixtures.latest.EURAMD.horizons.find((h) => h.label === "1M")!.ai_view!;
    expect(ai).toHaveTextContent("AI view · experimental");
    expect(within(ai).getByTestId("ai-prob")).toHaveTextContent("56% chance of a better rate if you wait 1M · confidence medium");
    expect(ai).toHaveTextContent(v.reasoning);
    expect(ai).toHaveTextContent("gemini-3.5-flash-lite · gemini · 21 Oct 2026, 15:39 UTC");
  });

  it("states an empty live track record honestly", () => {
    renderPanel();
    expect(within(row("1M")).getByTestId("ai-track")).toHaveTextContent(
      "Live track record: 0 of 250 forecasts scored. Unproven, does not decide the verdict.",
    );
    expect(row("1M")).toHaveAttribute("data-source", "statistical");
    expect(within(row("1M")).queryByTestId("verdict-source")).toBeNull();
  });

  it("adds the hit rate and Brier score once forecasts are scored", () => {
    renderPanel({ "1M": { ai_view: AI_VIEWS.scored } });
    expect(within(row("1M")).getByTestId("ai-track")).toHaveTextContent(
      "Live track record: 37 of 250 forecasts scored, hit rate 54.1%, Brier 0.243 (0.25 is a coin flip). Unproven, does not decide the verdict.",
    );
  });

  it("when promoted, says it decides the verdict and marks the verdict as coming from it", () => {
    renderPanel({ "1M": { signal: SIGNALS.aiDecides, ai_view: AI_VIEWS.promoted } });
    const r = row("1M");
    expect(r).toHaveAttribute("data-source", "ai");
    expect(within(r).getByTestId("signal-verdict")).toHaveTextContent("Wait");
    expect(within(r).getByTestId("verdict-source")).toHaveTextContent("Verdict from the AI view");
    expect(within(r).getByTestId("ai-track")).toHaveTextContent(
      "Live track record: 263 forecasts scored, hit rate 57.0%, Brier 0.231 (0.25 is a coin flip). Promoted: meets the same rule as the statistical models; it decides the verdict.",
    );
    expect(within(r).getByTestId("ai-view")).toHaveAttribute("data-promoted", "true");
  });

  it("shows one muted line when the AI view is off", () => {
    renderPanel({ "1M": { ai_view: null } });
    const ai = within(row("1M")).getByTestId("ai-view");
    expect(ai).toHaveTextContent(/^AI view off \(no forecast yet\)$/);
    // The statistical answer is unaffected.
    expect(within(row("1M")).getByTestId("signal-lead")).toBeInTheDocument();
  });
});
