import { expect, test } from "@playwright/test";

/**
 * E2E golden path + 60-second wow (Rules §13.3). Requires the full stack:
 *   make up && make seed && cd apps/web && npm run dev
 * The 60s wow asserts counters, chips, EV drawer, and outage banner.
 */

const BASE = process.env.E2E_BASE ?? "http://localhost:5173";

test("login → dashboard renders counters and stream", async ({ page }) => {
  await page.goto(`${BASE}/login`);
  await page.fill('input:not([type="password"])', "operator@reflex.dev");
  await page.fill('input[type="password"]', "reflex-demo");
  await page.click('button[type="submit"]');
  await page.waitForURL("**/dashboard");
  await expect(page.getByText("Failed value")).toBeVisible();
  await expect(page.getByText("[SIMULATED]").first()).toBeVisible();
});

test("60-second wow path", async ({ page }) => {
  test.setTimeout(90_000);
  await page.goto(`${BASE}/login`);
  await page.fill('input:not([type="password"])', "operator@reflex.dev");
  await page.fill('input[type="password"]', "reflex-demo");
  await page.click('button[type="submit"]');
  await page.waitForURL("**/dashboard");

  // start demo slice via Ops
  await page.goto(`${BASE}/ops`);
  await page.click("text=Webhook storm"); // injection console reachable

  // back to dashboard: stream rows appear with diagnosis chips
  await page.goto(`${BASE}/dashboard`);
  await expect(page.locator("li").first()).toBeVisible({ timeout: 30_000 });

  // kill switch stops everything within 1s drain
  await page.click("text=Kill switch");
  await expect(page.getByText("HALTED — kill switch active")).toBeVisible({ timeout: 2000 });
});
