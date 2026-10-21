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
    for (const label of ["1D", "1W", "1M"]) {
      await expect(page.getByTestId(`horizon-card-${label}`)).toContainText("Statistical estimate. Not financial advice.");
    }
  });

  test("hover readout shows the bands of a horizon", async ({ mockedPage: page }) => {
    await page.goto("/#/pair/EURUSD");
    const point = page.locator('[data-horizon-point="1M"]');
    // The FR-17 panel sits above the chart, so bring the chart into the viewport first.
    await page.getByTestId("fan-chart").scrollIntoViewIfNeeded();
    const box = (await point.boundingBox())!;
    await page.mouse.move(box.x + box.width / 2 - 1, box.y + box.height / 2);
    await expect(page.locator(".fan-readout")).toContainText("1M · 19 Nov 2026");
    await expect(page.locator(".fan-readout")).toContainText("1.0939 – 1.1482");
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
    await expect(warning).toContainText("Atlanta Fed Market Probability Tracker");
    await expect(warning).toContainText("last successful update 16 Oct 2026, 15:20 UTC");
  });

  test("shows 'never' for a source without a successful run, on every view", async ({ mockedPage: page }) => {
    for (const view of ["pair", "drivers", "events", "backtest"]) {
      await page.goto(`/#/${view}/USDAMD`);
      const warning = page.getByTestId("stale-warning");
      await expect(warning).toContainText("CBA decisions (cba.am, ARKA, Interfax) last successful update never");
      await expect(page.locator(".source-list li").first()).toBeVisible();
    }
  });
});

test.describe("EUR/AMD and the FR-17 indicator", () => {
  test("the EUR/AMD pair view shows the fan chart and the sell indicator", async ({ mockedPage: page }) => {
    await page.goto("/#/pair/EURAMD");
    await expect(page.getByRole("heading", { level: 1, name: "EUR/AMD" })).toBeVisible();
    await expect(page.getByTestId("fan-chart")).toBeVisible();
    await expect(page.locator("path[data-band]")).toHaveCount(3);
    await expect(page.getByTestId("history-line")).toHaveAttribute("data-points", "90");

    const panel = page.getByTestId("signal-panel");
    await expect(panel).toBeVisible();
    await expect(panel.getByRole("heading", { name: "Sell EUR now?" })).toBeVisible();
    for (const label of ["1D", "1W", "1M"]) {
      const row = page.getByTestId(`signal-${label}`);
      await expect(row.getByTestId("signal-verdict")).toHaveText("No clear edge");
      await expect(row.getByTestId("signal-lead")).toHaveText(`Waiting ${label} doesn\u2019t improve your expected rate`);
      await expect(row.getByTestId("signal-risk")).toContainText("AMD per \u20ac");
      await expect(row.getByTestId("signal-interest")).toContainText("Holding AMD pays ~4.50%/yr more than EUR");
      await expect(row.getByTestId("signal-prob")).toHaveText(`50% chance of a better rate if you wait ${label}`);
      const ai = row.getByTestId("ai-view");
      await expect(ai).toContainText("AI view");
      await expect(ai).toContainText("experimental");
      await expect(ai.getByTestId("ai-track")).toHaveText(
        "Live track record: 0 of 250 forecasts scored. Unproven, does not decide the verdict.",
      );
    }
    await expect(panel.getByTestId("disclaimer")).toHaveText("Statistical estimate. Not financial advice.");
    // The indicator sits above the fan chart.
    const panelBox = (await panel.boundingBox())!;
    const chartBox = (await page.getByTestId("fan-chart").boundingBox())!;
    expect(panelBox.y).toBeLessThan(chartBox.y);
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
    await expect(page.getByTestId("signal-panel")).toBeVisible();
    await expect(page.getByTestId("fan-chart")).toBeVisible();
    // One horizon at a time on a phone: 1M first, the others behind the horizon switch.
    await expect(page.getByTestId("signal-1M")).toBeVisible();
    await expect(page.getByTestId("signal-1D")).toBeHidden();
    await expect(page.getByTestId("signal-1M").getByText("experimental")).toBeVisible();
    await page.getByRole("group", { name: "Signal horizon" }).getByRole("button", { name: "1W" }).click();
    await expect(page.getByTestId("signal-1W")).toBeVisible();
    await expect(page.getByTestId("signal-1M")).toBeHidden();
    // The panel stays compact: the fan chart starts well within two screens of the top.
    const chartTop = await page.getByTestId("fan-chart").evaluate((el) => el.getBoundingClientRect().top + window.scrollY);
    expect(chartTop).toBeLessThan(1500);
    await page.getByTestId("signal-1W").getByText("Evidence behind the verdict").click();
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
    expect(band).toBe("rgb(57, 135, 229)");
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
