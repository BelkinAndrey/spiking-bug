import { test, expect } from "./fixtures";

test("create 200,000 neurons, fit the full ganglion and retain distant zoom", async ({
  page,
  request,
}) => {
  test.setTimeout(180_000);
  const original = await (
    await request.get("http://127.0.0.1:8010/api/project")
  ).json();
  try {
    const errors: string[] = [];
    page.on("pageerror", (error) => errors.push(error.message));
    await page.goto("http://127.0.0.1:5184");
    await expect(page.getByText("Синхронизировано")).toBeVisible();
    await page.locator("#new-ganglion").click();
    const form = page.locator("#ganglion-form");
    await form.locator('[name="count"]').fill("200000");
    await form.locator('[name="radius"]').fill("50000");
    await form.locator('[name="density"]').fill("0");
    await form.locator('[name="x"]').fill("0");
    await form.locator('[name="y"]').fill("0");
    await form.getByRole("button", { name: "Сгенерировать ганглий" }).click();
    await expect(page.locator(".live-values")).toHaveText(
      "200000 нейронов · r = 50000",
      { timeout: 120_000 },
    );
    await page.locator("#fit").click();
    const readCamera = () =>
      page.evaluate(() =>
        JSON.parse(localStorage.getItem("spiking-bug.camera.editor")!),
      );
    const camera = await readCamera();
    const bounds = (await page.locator("#scene").boundingBox())!;
    expect(camera.zoom).toBeLessThan(0.05);
    expect(camera.x - 50000 * camera.zoom).toBeGreaterThanOrEqual(0);
    expect(camera.y - 50000 * camera.zoom).toBeGreaterThanOrEqual(0);
    expect(camera.x + 50000 * camera.zoom).toBeLessThanOrEqual(bounds.width);
    expect(camera.y + 50000 * camera.zoom).toBeLessThanOrEqual(bounds.height);
    // One wheel gesture reaches the lower clamp without hundreds of clicks.
    await page
      .locator("#scene")
      .dispatchEvent("wheel", { deltaY: 100000, clientX: 400, clientY: 400 });
    expect((await readCamera()).zoom).toBe(0.0005);
    await page.reload();
    await expect(page.getByText("Синхронизировано")).toBeVisible({
      timeout: 60_000,
    });
    expect((await readCamera()).zoom).toBe(0.0005);
    await page.locator("#zoom-in").click();
    expect((await readCamera()).zoom).toBeGreaterThan(0.0005);
    expect(errors).toEqual([]);
  } finally {
    await page.close();
    const state = await (
      await request.get("http://127.0.0.1:8010/api/state")
    ).json();
    const restored = await request.post("http://127.0.0.1:8010/api/command", {
      data: { action: "import", data: original, revision: state.revision },
    });
    expect(restored.ok()).toBeTruthy();
  }
});
