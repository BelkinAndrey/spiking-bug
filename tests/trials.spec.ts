import { test, expect } from "./fixtures";

test("trial dialog runs isolated attempts, exports results and resumes a cancelled job", async ({
  page,
  request,
}) => {
  const base = "http://127.0.0.1:8010";
  const project = async () => (await request.get(base + "/api/project")).json();
  const original = await project();
  const command = async (action: string, data: unknown) => {
    const p = await project();
    const response = await request.post(base + "/api/command", {
      data: { action, data, revision: p.revision },
    });
    expect(response.ok()).toBeTruthy();
  };
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  try {
    await command("control", { mode: "pause" });
    await command("topology", {
      neurons: [{ id: "motor", bias: 2 }],
      synapses: [],
    });
    await command("bindings", { forward: "motor" });
    const before = await project();
    const stateBefore = await (await request.get(base + "/api/state")).json();
    await page.goto("http://127.0.0.1:5183");
    await expect(page.getByText("Синхронизировано")).toBeVisible();
    await page.getByRole("button", { name: "Испытание", exact: true }).click();
    const dialog = page.getByRole("dialog", {
      name: "Испытание нейронной сети",
    });
    await dialog.getByLabel("Количество попыток").fill("3");
    await dialog.getByLabel("Длительность попытки, с").fill("2");
    await dialog.getByLabel("Начальный seed").fill("123");
    await dialog
      .getByRole("button", { name: "Запустить испытание", exact: true })
      .click();
    await expect(dialog.locator("#trials-status")).toHaveText(
      "Испытание завершено",
      { timeout: 20000 },
    );
    await expect(dialog.locator("#trials-count")).toHaveText("3 / 3");
    await expect(dialog.getByRole("progressbar")).toHaveAttribute("value", "1");
    await expect(dialog.locator("tbody tr")).toHaveCount(3);
    await expect(dialog.locator("tbody tr").first()).toContainText("1 / 123");
    await expect(dialog.locator("#trials-metrics")).toContainText(
      "Выживаемость",
    );
    expect(await project()).toEqual(before);
    const stateAfter = await (await request.get(base + "/api/state")).json();
    expect(stateAfter.t).toBe(stateBefore.t);
    expect(stateAfter.world).toEqual(stateBefore.world);
    expect(stateAfter.activity).toEqual(stateBefore.activity);
    const downloadPromise = page.waitForEvent("download");
    await dialog.getByRole("button", { name: "CSV", exact: true }).click();
    const download = await downloadPromise;
    expect(download.suggestedFilename()).toBe("trials.csv");
    await download.saveAs("test-results/trials.csv");
    await page.screenshot({ path: "test-results/trials-desktop.png" });
    await page.setViewportSize({ width: 390, height: 844 });
    await expect(dialog).toBeInViewport();
    const rect = (await dialog.boundingBox())!;
    expect(rect.x).toBeGreaterThanOrEqual(0);
    expect(rect.x + rect.width).toBeLessThanOrEqual(390);
    await page.screenshot({ path: "test-results/trials-mobile.png" });
    await dialog.getByLabel("Количество попыток").fill("1000");
    await dialog.getByLabel("Длительность попытки, с").fill("3600");
    await dialog
      .getByRole("button", { name: "Запустить испытание", exact: true })
      .click();
    await expect(dialog.getByLabel("Количество попыток")).toBeDisabled();
    await dialog.getByRole("button", { name: "Закрыть", exact: true }).click();
    await page.getByRole("button", { name: "Испытание", exact: true }).click();
    await expect(dialog.getByLabel("Количество попыток")).toHaveValue("1000");
    await expect(
      dialog.getByRole("button", { name: "Остановить испытание", exact: true }),
    ).toBeVisible();
    await dialog
      .getByRole("button", { name: "Остановить испытание", exact: true })
      .click();
    await expect(dialog.locator("#trials-status")).toHaveText(
      "Испытание остановлено",
      { timeout: 10000 },
    );
    await expect(dialog.getByLabel("Количество попыток")).toBeEnabled();
    await dialog.getByRole("button", { name: "Закрыть", exact: true }).click();
    await page.locator("#language").selectOption("en");
    await page.getByRole("button", { name: "Trial", exact: true }).click();
    await expect(page.getByRole("dialog")).toContainText("Trial stopped");
    await page.route("**/api/trials", (route) =>
      route.fulfill({ contentType: "application/json", body: "null" }),
    );
    await expect(page.locator("#trials-progress")).toBeHidden();
    await expect(page.locator("#trials-results")).toBeHidden();
    await page.unroute("**/api/trials");
    await page.route("**/api/trials", (route) =>
      route.fulfill({ status: 404, body: "Not found" }),
    );
    await expect(page.locator("#trials-error")).toContainText(
      "Restart the application server",
    );
    expect(errors).toEqual([]);
  } finally {
    const job = await (await request.get(base + "/api/trials")).json();
    if (job)
      await request.post(base + "/api/trials/cancel", { data: { id: job.id } });
    await page.close();
    await command("import", original);
  }
});
