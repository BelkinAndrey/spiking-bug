import { test, expect } from "./fixtures";

test("zero-health warning appears on the arena and clears after recovery", async ({
  page,
  request,
}) => {
  const state = await (
    await request.get("http://127.0.0.1:8010/api/state")
  ).json();
  state.world.agent.health = 0;
  // Drive the visual state without changing the shared test world's physiology.
  await page.route("**/api/events", async (route) => {
    await route.fulfill({
      contentType: "text/event-stream",
      body: `data: ${JSON.stringify(state)}\n\n`,
    });
  });
  await page.goto("http://127.0.0.1:5183");
  const warning = page.locator("#health-warning");
  await expect(warning).toBeVisible();
  await expect(warning).toContainText("Нет здоровья");
  await expect(warning).toContainText("Движение продолжается");
  await expect(page.locator("#health")).toHaveText("0");
  await page.screenshot({ path: "test-results/zero-health-desktop.png" });
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(warning).toBeInViewport();
  const rect = (await warning.boundingBox())!;
  const toolbar = (await page.locator("#tools").boundingBox())!;
  expect(rect.y).toBeGreaterThan(toolbar.y + toolbar.height);
  expect(rect.x).toBeGreaterThanOrEqual(0);
  expect(rect.x + rect.width).toBeLessThanOrEqual(390);
  await page.screenshot({
    path: "test-results/zero-health-mobile.png",
    fullPage: true,
  });
  await page.locator("#language").selectOption("en");
  await expect(warning).toHaveText("No healthMovement continues");
  state.world.agent.health = 0.12;
  await page.reload();
  await expect(page.locator("#health")).toHaveText("12");
  await expect(warning).toBeHidden();
});
