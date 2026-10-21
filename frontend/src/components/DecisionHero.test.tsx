import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { LatestForecastResponse } from "../api/types";
import { PAIRS } from "../lib/constants";
import { AI_VIEWS, SIGNALS, latestWith } from "../mocks/signals";
import { DecisionHero, verdictSentence } from "./DecisionHero";

function renderHero(forecast: LatestForecastResponse, selected = "1M", onSelect = vi.fn()) {
  render(<DecisionHero pair={PAIRS.EURAMD} forecast={forecast} selected={selected} onSelect={onSelect} />);
  return { hero: screen.getByTestId("decision-hero"), onSelect };
}

describe("DecisionHero (FR-17)", () => {
  it("asks the question for the pair and phrases the horizons as the user's need", () => {
    const { hero } = renderHero(latestWith({}));
    expect(within(hero).getByRole("heading", { level: 1 })).toHaveTextContent("Sell EUR for AMD now?");
    const buttons = within(hero).getAllByRole("button", { pressed: undefined }).filter((b) => b.className.includes("seg"));
    expect(buttons.map((b) => b.textContent)).toEqual(["tomorrow", "within a week", "within a month"]);
  });

  it.each([
    ["sellNow", "Sell now", "59% chance the rate is lower"],
    ["unproven", "Wait", "chance the rate is higher"],
    ["noLean", "No clear answer", "Close to even: 52% chance the rate is higher"],
  ] as const)("the %s AI view reads '%s' with the probability on the side it favours", (key, verdict, sentence) => {
    const { hero } = renderHero(latestWith({ "1M": { ai_view: AI_VIEWS[key] } }));
    expect(within(hero).getByTestId("verdict")).toHaveTextContent(verdict);
    expect(within(hero).getByTestId("verdict-sentence")).toHaveTextContent(sentence);
    expect(hero.dataset.lean).toBe(AI_VIEWS[key].lean);
  });

  it("without an AI view the answer is 'No clear answer' and no probability is shown", () => {
    const { hero } = renderHero(latestWith({ "1M": { ai_view: null } }));
    expect(within(hero).getByTestId("verdict")).toHaveTextContent("No clear answer");
    expect(within(hero).getByTestId("verdict-sentence")).toHaveTextContent("No model has proven an edge");
    expect(hero.textContent).not.toMatch(/\d+% chance/);
    expect(within(hero).queryByTestId("ai-tag")).toBeNull();
  });

  it("labels an unproven AI view honestly and opens its evidence on demand", () => {
    const { hero } = renderHero(latestWith({ "1M": { ai_view: AI_VIEWS.unproven } }));
    const tag = within(hero).getByTestId("ai-tag");
    expect(tag).toHaveTextContent("Gemini AI view, not yet proven (0 of 250 checked)");
    expect(within(hero).queryByTestId("hero-evidence")).toBeNull();
    fireEvent.click(tag);
    expect(within(hero).getByTestId("ai-track")).toHaveTextContent("Unproven, so it does not decide the verdict.");
  });

  it("a promoted AI view says it is proven", () => {
    const { hero } = renderHero(latestWith({ "1M": { ai_view: AI_VIEWS.promoted, signal: SIGNALS.aiDecides } }));
    expect(within(hero).getByTestId("ai-tag")).toHaveTextContent("proven on 263 live forecasts");
    expect(within(hero).getByTestId("fact-stat")).toHaveTextContent("Verdict comes from the promoted AI view");
  });

  it("the facts row carries the risk of waiting, the interest difference and the statistical answer", () => {
    const { hero } = renderHero(latestWith({ "1M": { signal: SIGNALS.noEdgeNone } }));
    expect(within(hero).getByTestId("fact-wait")).toHaveTextContent(/ to .* AMD per €, 80% range/);
    expect(within(hero).getByTestId("fact-interest")).toHaveTextContent(/AMD pays .*%\/yr more than EUR/);
    expect(within(hero).getByTestId("fact-stat")).toHaveTextContent("No proven edge");
  });

  it("names the currency that pays more when the carry is negative, and drops the line when unknown", () => {
    renderHero(latestWith({ "1M": { signal: SIGNALS.negativeCarry } }));
    expect(screen.getByTestId("fact-interest")).toHaveTextContent(/^.*EUR pays .*%\/yr more than AMD/);
  });

  it("hides the interest line when the carry is unknown", () => {
    renderHero(latestWith({ "1M": { signal: SIGNALS.nullCarry } }));
    expect(screen.queryByTestId("fact-interest")).toBeNull();
  });

  it("selecting a horizon reports it", () => {
    const { hero, onSelect } = renderHero(latestWith({}));
    fireEvent.click(within(hero).getByRole("button", { name: "tomorrow" }));
    expect(onSelect).toHaveBeenCalledWith("1D");
  });

  it("keeps the disclaimer on the decision", () => {
    const { hero } = renderHero(latestWith({}));
    expect(hero).toHaveTextContent("Statistical estimate. Not financial advice.");
  });

  it("verdictSentence flips to the favoured side for sell now", () => {
    const h = latestWith({}).horizons.find((x) => x.label === "1M")!;
    expect(verdictSentence({ ...AI_VIEWS.sellNow, prob_better_if_wait: 0.45 }, h)).toMatch(/^55% chance the rate is lower by /);
  });
});
