import { expect, test } from "@playwright/test";

// VITE_USE_MOCKS=1: the app serves fixture data without a backend and says so on every page.
test("mock mode is clearly labelled and works without the API", async ({ page }) => {
  const apiCalls: string[] = [];
  page.on("request", (r) => {
    if (new URL(r.url()).pathname.startsWith("/api/")) apiCalls.push(r.url());
  });
  await page.goto("/#/pair/EURUSD");
  await expect(page.getByTestId("mock-banner")).toContainText("Mock mode");
  await expect(page.getByText("Mock data", { exact: true })).toBeVisible();
  await expect(page.getByTestId("fan-chart")).toBeVisible();
  await page.getByRole("link", { name: "Events" }).click();
  await expect(page.getByTestId("decision-list")).toBeVisible();
  await expect(page.getByTestId("mock-banner")).toBeVisible();
  expect(apiCalls).toEqual([]);
});
