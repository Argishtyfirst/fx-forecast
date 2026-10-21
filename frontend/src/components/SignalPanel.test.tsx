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
const fixture = (label: string) => fixtures.latest.EURAMD.horizons.find((h) => h.label === label)!;

describe("SignalPanel (FR-17): AI view as the headline", () => {
  it("asks the question with the base currency and has one answer per horizon", () => {
    renderPanel();
    const panel = screen.getByTestId("signal-panel");
    expect(within(panel).getByRole("heading", { name: "Sell EUR now?" })).toBeInTheDocument();
    expect(["1D", "1W", "1M"].map((l) => row(l).dataset.lead)).toEqual(["ai", "ai", "ai"]);
  });

  it.each([
    ["1D", "Yes, sell now", "44%"],
    ["1W", "No clear lean", "52%"],
    ["1M", "Wait", "58%"],
  ])("%s leads with the AI's call: %s, %s", (label, verdict, pct) => {
    renderPanel();
    const r = row(label);
    expect(within(r).getByTestId("signal-verdict")).toHaveTextContent(new RegExp(`^${verdict}$`));
    expect(within(r).getByTestId("signal-prob")).toHaveTextContent(`${pct} chance of a better rate if you wait ${label}`);
    expect(within(r).getByTestId("ai-reasoning")).toHaveTextContent(fixture(label).ai_view!.reasoning);
  });

  it("shows the AI confidence on a low/medium/high scale", () => {
    renderPanel();
    const scale = within(row("1M")).getByTestId("confidence-scale");
    expect(scale).toHaveAccessibleName("Confidence");
    expect(within(scale).getAllByRole("listitem").map((li) => li.textContent)).toEqual(["low", "medium", "high"]);
    expect(within(scale).getByText("medium")).toHaveAttribute("aria-current", "true");
  });

  it("attaches an honest tag: experimental and unproven, with the model and time in its tooltip", () => {
    renderPanel();
    const tag = within(row("1M")).getByTestId("ai-tag");
    expect(tag).toHaveTextContent("AI view · experimental · unproven (0 of 250 forecasts scored)");
    expect(tag).toHaveAttribute("title", expect.stringContaining("gemini-3.5-flash-lite · gemini"));
    expect(tag.getAttribute("title")).toContain("21 Oct 2026, 15:39 UTC");
  });

  it("says when the AI view is proven, and that it decides the verdict", () => {
    renderPanel({ "1M": { signal: SIGNALS.aiDecides, ai_view: AI_VIEWS.promoted } });
    const r = row("1M");
    expect(within(r).getByTestId("ai-tag")).toHaveTextContent("AI view · proven on 263 live forecasts");
    expect(within(r).getByTestId("signal-stat")).toHaveTextContent("Verdict decided by the promoted AI view");
    expect(within(r).getByTestId("ai-track")).toHaveTextContent(
      "Live track record: 263 forecasts scored, hit rate 57.0%, Brier 0.231 (0.25 is a coin flip). Promoted: meets the same rule as the statistical models; it decides the verdict.",
    );
  });

  it("adds the hit rate and Brier score in the evidence once forecasts are scored", () => {
    renderPanel({ "1M": { ai_view: AI_VIEWS.scored } });
    expect(within(row("1M")).getByTestId("ai-tag")).toHaveTextContent("unproven (37 of 250 forecasts scored)");
    expect(within(row("1M")).getByTestId("ai-track")).toHaveTextContent(
      "Live track record: 37 of 250 forecasts scored, hit rate 54.1%, Brier 0.243 (0.25 is a coin flip). Unproven, does not decide the verdict.",
    );
  });

  it.each([
    ["sell_now", AI_VIEWS.sellNow, "Yes, sell now", "41%"],
    ["no_edge", AI_VIEWS.noLean, "No clear lean", "52%"],
  ])("renders an AI %s lean", (_n, ai, verdict, pct) => {
    renderPanel({ "1M": { ai_view: ai } });
    expect(within(row("1M")).getByTestId("signal-verdict")).toHaveTextContent(verdict);
    expect(within(row("1M")).getByTestId("signal-prob")).toHaveTextContent(`${pct} chance`);
  });

  it("puts the statistical models in one secondary line, with no bare 50%", () => {
    renderPanel();
    const s = fixture("1M").signal!;
    const stat = within(row("1M")).getByTestId("signal-stat");
    expect(stat).toHaveTextContent(
      `Statistical models: no proven edge · risk of waiting ±2.6% (${s.downside_p10_rate.toFixed(2)} – ${s.upside_p90_rate.toFixed(2)} AMD per €) · AMD pays ~4.50%/yr more than EUR`,
    );
    expect(screen.getByTestId("signal-panel")).not.toHaveTextContent(/50% chance/);
  });

  it("shows a statistical lean's verdict and probability in that line instead", () => {
    renderPanel({ "1M": { signal: SIGNALS.waitMedium } });
    expect(within(row("1M")).getByTestId("signal-stat")).toHaveTextContent(
      "Statistical models: wait, 58% chance of a better rate if you wait 1M (confidence medium)",
    );
  });

  it("names the currency that pays more, and drops the interest when unknown", () => {
    const { unmount } = renderPanel({ "1M": { signal: SIGNALS.negativeCarry } });
    expect(within(row("1M")).getByTestId("signal-interest")).toHaveTextContent("EUR pays ~4.50%/yr more than AMD");
    unmount();
    renderPanel({ "1M": { signal: SIGNALS.nullCarry } });
    expect(within(row("1M")).queryByTestId("signal-interest")).toBeNull();
  });
});

describe("SignalPanel: without an AI view", () => {
  it("leads with no proven edge, the risk and the interest; never a bare 50%", () => {
    renderPanel({ "1M": { ai_view: null } });
    const r = row("1M");
    expect(r).toHaveAttribute("data-lead", "statistical");
    expect(within(r).getByTestId("signal-verdict")).toHaveTextContent(/^No proven edge$/);
    expect(within(r).getByTestId("signal-lead")).toHaveTextContent("Waiting 1M doesn’t improve your expected rate");
    expect(within(r).getByTestId("signal-risk")).toHaveTextContent("±2.6%");
    expect(within(r).getByTestId("signal-interest")).toHaveTextContent(
      "Holding AMD pays ~4.50%/yr more than EUR (~1.52 AMD per € over 1M)",
    );
    expect(r).toHaveTextContent("at policy rates; your bank’s rates differ");
    expect(within(r).getByTestId("ai-view-off")).toHaveTextContent(/^AI view: no forecast yet$/);
    expect(within(r).queryByTestId("signal-prob")).toBeNull();
    expect(r).not.toHaveTextContent(/\b50% chance/);
  });

  it.each([
    ["wait", SIGNALS.waitMedium, "Wait", "58%"],
    ["sell_now", SIGNALS.sellNowHigh, "Yes, sell now", "31%"],
  ])("a statistical %s lean leads with its verdict and probability", (_n, signal, verdict, pct) => {
    renderPanel({ "1M": { signal, ai_view: null } });
    expect(within(row("1M")).getByTestId("signal-verdict")).toHaveTextContent(verdict);
    expect(within(row("1M")).getByTestId("signal-prob")).toHaveTextContent(`${pct} chance of a better rate if you wait 1M`);
  });
});

describe("SignalPanel: frame", () => {
  it("carries the disclaimer", () => {
    renderPanel();
    expect(within(screen.getByTestId("signal-panel")).getByTestId("disclaimer")).toHaveTextContent(DISCLAIMER);
  });

  it("keeps the statistical evidence in the expander", async () => {
    renderPanel();
    const r = row("1W");
    await userEvent.click(within(r).getByText("Evidence"));
    const evidence = r.querySelector("details")!;
    expect(evidence).toHaveAttribute("open");
    expect(evidence).toHaveTextContent(fixture("1W").signal!.summary);
    expect(evidence).toHaveTextContent("Beats random walkNo");
    expect(within(r).getByTestId("signal-downside")).toHaveTextContent(`≤ ${fixture("1W").signal!.downside_p10_rate.toFixed(2)}`);
  });

  it("hides a horizon without a signal, and the whole panel when none has one", () => {
    const { unmount } = renderPanel({ "1D": { signal: null } });
    expect(screen.queryByTestId("signal-1D")).toBeNull();
    unmount();
    const { container } = renderPanel({ "1D": { signal: null }, "1W": { signal: null }, "1M": { signal: null } });
    expect(container).toBeEmptyDOMElement();
  });

  it("offers one horizon at a time on small screens (1M first)", async () => {
    renderPanel();
    const tabs = screen.getByRole("group", { name: "Signal horizon" });
    expect(within(tabs).getByRole("button", { name: "1M" })).toHaveAttribute("aria-pressed", "true");
    expect(row("1M")).toHaveClass("is-active");
    await userEvent.click(within(tabs).getByRole("button", { name: "1D" }));
    expect(row("1D")).toHaveClass("is-active");
    expect(row("1M")).not.toHaveClass("is-active");
  });
});
