import { mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { routeApi, test, NOW } from "./fixtures";

// Visual QA: every view at 1280px and 380px, light and dark, saved to frontend/screenshots/.
const OUT = join(dirname(fileURLToPath(import.meta.url)), "..", "screenshots");
mkdirSync(OUT, { recursive: true });

const VIEWS = [
  { name: "pair", hash: "#/pair/EURUSD" },
  { name: "pair-usdamd", hash: "#/pair/USDAMD" },
  { name: "pair-euramd", hash: "#/pair/EURAMD" },
  { name: "drivers", hash: "#/drivers/EURUSD/1M" },
  { name: "events", hash: "#/events/EURUSD" },
  { name: "events-euramd", hash: "#/events/EURAMD" },
  { name: "backtest", hash: "#/backtest/EURUSD" },
];
const WIDTHS = [1280, 380];
const SCHEMES = ["light", "dark"] as const;

for (const scheme of SCHEMES) {
  for (const width of WIDTHS) {
    test.describe(`${scheme} ${width}px`, () => {
      test.use({ colorScheme: scheme, viewport: { width, height: width > 600 ? 900 : 820 } });
      for (const v of VIEWS) {
        test(`screenshot ${v.name}`, async ({ page }) => {
          await page.clock.setFixedTime(NOW);
          await routeApi(page);
          await page.goto(`/${v.hash}`);
          await page.locator(".view").waitFor();
          await page.waitForLoadState("networkidle");
          if (v.name === "events") {
            await page.getByRole("button", { name: /Statement changes/ }).first().click();
          }
          // Let the entry animation settle.
          await page.waitForTimeout(700);
          await page.screenshot({ path: join(OUT, `${v.name}-${width}-${scheme}.png`), fullPage: true });
        });
      }
    });
  }
}
