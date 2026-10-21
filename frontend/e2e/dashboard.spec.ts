import { expect, routeApi, test, NOW } from "./fixtures";

test.describe("FR-14 fan chart", () => {
  test("shows 90 trading days of history and the bands for all 3 horizons", async ({ mockedPage: page }) => {
    await page.goto("/#/pair/EURUSD");
    const chart = page.getByTestId("fan-chart");
    await expect(chart).toBeVisible();

    await expect(page.getByTestId("history-line")).toHaveAttribute("data-points", "90");
    await expect(chart).toHaveAttribute("aria-label", /90 trading days of history from 18 Jun 2026 to 21 Oct 2026/);

    const bands = page.locator("path[data-band]");
    await expect(bands).toHaveCount(3);
    for (const key of ["95", "80", "50"]) {
      const band = page.locator(`path[data-band="${key}"]`);
      await expect(band).toHaveAttribute("data-horizons", "1D 1W 1M");
      const box = await band.boundingBox();
      expect(box!.width).toBeGreaterThan(50);
      expect(box!.height).toBeGreaterThan(10);
    }
    // Bands are nested: the 95% band is the tallest, the 50% band the shortest.
    const heights = await Promise.all(
      ["95", "80", "50"].map(async (k) => (await page.locator(`path[data-band="${k}"]`).boundingBox())!.height),
    );
    expect(heights[0]).toBeGreaterThan(heights[1]);
    expect(heights[1]).toBeGreaterThan(heights[2]);

    await expect(page.locator("[data-horizon-point]")).toHaveCount(3);
    await expect(page.getByTestId("meeting-marker")).toHaveCount(2);
    await expect(page.getByTestId("decision-hero")).toContainText("Statistical estimate. Not financial advice.");
    await expect(page.getByTestId("ranges")).toContainText("Statistical estimate. Not financial advice.");
  });

  test("hover readout shows the bands of a horizon", async ({ mockedPage: page }) => {
    await page.goto("/#/pair/EURUSD");
    const point = page.locator('[data-horizon-point="1M"]');
    // The FR-17 panel sits above the chart, so bring the chart into the viewport first.
    await page.getByTestId("fan-chart").scrollIntoViewIfNeeded();
    const box = (await point.boundingBox())!;
    await page.mouse.move(box.x + box.width / 2 - 1, box.y + box.height / 2);
    await expect(page.locator(".fan-readout")).toContainText("1M, 19 Nov 2026");
    await expect(page.locator(".fan-readout")).toContainText("1.0939 to 1.1482");
  });

  test("a missing forecast is an empty state", async ({ page }) => {
    await page.clock.setFixedTime(NOW);
    await routeApi(page, { "/api/forecasts/EURUSD/latest": { status: 404, body: { detail: "No forecast yet" } } });
    await page.goto("/#/pair/EURUSD");
    await expect(page.getByText("No forecast yet")).toBeVisible();
    await expect(page.getByTestId("history-line")).toHaveAttribute("data-points", "90");
  });
});

test.describe("FR-16 stale data warning", () => {
  test("names the stale source and shows its last successful update time", async ({ mockedPage: page }) => {
    await page.goto("/#/pair/EURUSD");
    const warning = page.getByTestId("stale-warning");
    await expect(warning).toBeVisible();
    await expect(warning).toContainText("Atlanta Fed, last successful update 16 Oct 2026, 15:20 UTC");
  });

  test("shows 'never' for a source without a successful run, on every view", async ({ mockedPage: page }) => {
    for (const view of ["pair", "drivers", "events", "backtest"]) {
      await page.goto(`/#/${view}/USDAMD`);
      const warning = page.getByTestId("stale-warning");
      await expect(warning).toContainText("CBA news, last successful update never");
      await expect(page.getByTestId("data-summary")).toContainText("Data updated");
    }
  });
});

test.describe("EUR/AMD and the FR-17 indicator", () => {
  test("the EUR/AMD pair view shows the fan chart and the sell indicator", async ({ mockedPage: page }) => {
    await page.goto("/#/pair/EURAMD");
    await expect(page.getByRole("heading", { level: 1, name: "Sell EUR for AMD now?" })).toBeVisible();
    await expect(page.getByTestId("fan-chart")).toBeVisible();
    await expect(page.locator("path[data-band]")).toHaveCount(3);
    await expect(page.getByTestId("history-line")).toHaveAttribute("data-points", "90");

    const hero = page.getByTestId("decision-hero");
    await expect(hero.getByRole("heading", { name: "Sell EUR for AMD now?" })).toBeVisible();
    // Default horizon: within a month.
    await expect(hero.getByTestId("verdict")).toHaveText("Wait");
    await expect(hero.getByTestId("verdict-sentence")).toHaveText("58% chance the rate is higher by 19 Nov.");
    await expect(hero.getByTestId("ai-tag")).toHaveText("Gemini AI view, not yet proven (0 of 250 checked)");
    await expect(hero.getByTestId("fact-wait")).toContainText("394.73 to 415.62 AMD per \u20ac, 80% range");
    await expect(hero.getByTestId("fact-stat")).toContainText("No proven edge");
    await expect(hero.getByTestId("disclaimer")).toHaveText("Statistical estimate. Not financial advice.");
    await expect(hero).not.toContainText("50% chance");
    // The AI path on the chart: spot plus three horizons, with the chosen one labelled.
    await expect(page.getByTestId("ai-path")).toHaveAttribute("data-points", "4");
    await expect(page.getByTestId("ai-label")).toHaveText("AI: 406.88 by 19 Nov (Wait)");
    await hero.getByRole("button", { name: "tomorrow" }).click();
    await expect(hero.getByTestId("verdict")).toHaveText("Sell now");
    await expect(page.getByTestId("ai-label")).toHaveText("AI: 404.75 by 22 Oct (Sell now)");
    // The hero sits before the chart.
    const heroBox = (await hero.boundingBox())!;
    const chartBox = (await page.getByTestId("fan-chart").boundingBox())!;
    expect(heroBox.y).toBeLessThanOrEqual(chartBox.y);
  });

  test("the pair switch lists the three pairs", async ({ mockedPage: page }) => {
    await page.goto("/#/pair/EURUSD");
    const sw = page.getByRole("group", { name: "Currency pair" });
    await expect(sw.getByRole("link")).toHaveText(["EUR/USD", "USD/AMD", "EUR/AMD"]);
    await sw.getByRole("link", { name: "EUR/AMD" }).click();
    await expect(page).toHaveURL(/#\/pair\/EURAMD$/);
  });
});

test.describe("380px screen", () => {
  test.use({ viewport: { width: 380, height: 800 } });
  test("EUR/AMD pair view has no horizontal page scroll and the pair switch fits", async ({ mockedPage: page }) => {
    await page.goto("/#/pair/EURAMD");
    const hero = page.getByTestId("decision-hero");
    await expect(hero).toBeVisible();
    await expect(page.getByTestId("fan-chart")).toBeVisible();
    // The verdict is readable without scrolling.
    const verdictBox = (await hero.getByTestId("verdict").boundingBox())!;
    expect(verdictBox.y + verdictBox.height).toBeLessThan(800);
    await hero.getByTestId("ai-tag").click();
    await expect(hero.getByTestId("hero-evidence")).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(380);
    const sw = (await page.getByRole("group", { name: "Currency pair" }).boundingBox())!;
    expect(sw.x).toBeGreaterThanOrEqual(0);
    expect(sw.x + sw.width).toBeLessThanOrEqual(380 - 16);
  });

  for (const view of ["pair", "drivers", "events", "backtest"]) {
    test(`${view} view has no horizontal page scroll`, async ({ mockedPage: page }) => {
      await page.goto(`/#/${view}/EURUSD`);
      await page.locator(".view").waitFor();
      await page.waitForLoadState("networkidle");
      if (view === "events") await page.getByRole("button", { name: /Statement changes/ }).first().click();
      const scrollWidth = await page.evaluate(() => document.documentElement.scrollWidth);
      expect(scrollWidth).toBeLessThanOrEqual(380);
    });
  }
});

test.describe("dark mode", () => {
  test.use({ colorScheme: "dark" });
  test("follows prefers-color-scheme", async ({ mockedPage: page }) => {
    await page.goto("/#/pair/EURUSD");
    await expect(page.getByTestId("fan-chart")).toBeVisible();
    const bg = await page.evaluate(() => getComputedStyle(document.body).backgroundColor);
    expect(bg).toBe("rgb(20, 20, 19)");
    const band = await page.locator('path[data-band="50"]').evaluate((el) => getComputedStyle(el).fill);
    expect(band).toBe("rgb(68, 68, 63)");
    const ai = await page.getByTestId("ai-path").evaluate((el) => getComputedStyle(el).stroke);
    expect(ai).toBe("rgb(134, 168, 255)");
  });
});

test("the theme toggle persists across reloads", async ({ mockedPage: page }) => {
  await page.emulateMedia({ colorScheme: "light" });
  await page.goto("/#/pair/EURUSD");
  expect(await page.evaluate(() => getComputedStyle(document.body).backgroundColor)).toBe("rgb(247, 246, 243)");
  await page.getByTestId("theme-toggle").click();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  await page.reload();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  expect(await page.evaluate(() => getComputedStyle(document.body).backgroundColor)).toBe("rgb(20, 20, 19)");
});

test("views are URL-addressable", async ({ mockedPage: page }) => {
  await page.goto("/");
  await expect(page).toHaveURL(/#\/pair\/EURUSD$/);
  await page.getByRole("link", { name: "Backtest" }).click();
  await expect(page).toHaveURL(/#\/backtest\/EURUSD$/);
  await page.getByRole("link", { name: "USD/AMD" }).click();
  await expect(page).toHaveURL(/#\/backtest\/USDAMD$/);
  await expect(page.getByTestId("backtest-1M")).toContainText("Forward rate");
  await page.goBack();
  await expect(page).toHaveURL(/#\/backtest\/EURUSD$/);
});
