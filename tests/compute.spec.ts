import { test, expect } from "@playwright/test";

test("device selection is explicit and shared between clients", async ({
  page,
  context,
  request,
}) => {
  const api = "http://127.0.0.1:8010";
  const capabilities = await (await request.get(api + "/api/devices")).json();
  const gpu = capabilities.devices.find(
    (d: any) => d.available && d.id !== "cpu",
  );
  const command = async (action: string, data: unknown) => {
    const p = await (await request.get(api + "/api/project")).json();
    const res = await request.post(api + "/api/command", {
      data: { action, data, revision: p.revision },
    });
    expect(res.ok()).toBeTruthy();
  };
  await command("control", { mode: "pause" });
  await command("compute", { device: "cpu" });
  await page.goto("http://127.0.0.1:5184");
  const select = page.getByLabel("Устройство расчёта");
  await expect(select).toBeEnabled();
  await expect(select).toHaveValue("cpu");
  for (const option of capabilities.devices.filter((d: any) => !d.available))
    await expect(select.locator(`option[value="${option.id}"]`)).toBeDisabled();
  const environment = await context.newPage();
  await environment.goto("http://127.0.0.1:5183");
  await expect(environment.getByLabel("Устройство расчёта")).toBeEnabled();
  if (gpu) {
    try {
      const before = await (await request.get(api + "/api/state")).json();
      await select.selectOption(gpu.id);
      await expect(environment.getByLabel("Устройство расчёта")).toHaveValue(
        gpu.id,
      );
      await expect(page.locator("#version")).toContainText("PyTorch");
      const after = await (await request.get(api + "/api/state")).json();
      expect(after.activity).toEqual(before.activity);
      expect(after.t).toEqual(before.t);
      expect(after.world).toEqual(before.world);
      await page.screenshot({ path: "test-results/gpu-editor.png" });
      await page
        .getByRole("button", { name: "▶ Запустить", exact: true })
        .click();
      await expect
        .poll(
          async () => (await (await request.get(api + "/api/state")).json()).t,
        )
        .toBeGreaterThan(before.t);
      await environment.getByLabel("Устройство расчёта").selectOption("cpu");
      await expect(select).toHaveValue("cpu");
      await expect(page.locator("#version")).toContainText("NumPy");
      await expect(
        page.getByRole("button", { name: "Ⅱ Пауза", exact: true }),
      ).toBeVisible();
    } finally {
      await command("control", { mode: "pause" });
      await command("compute", { device: "cpu" });
    }
  }
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(select).toBeVisible();
  expect(
    await page.evaluate(() => document.documentElement.scrollWidth),
  ).toBeLessThanOrEqual(390);
  await page.screenshot({
    path: "test-results/compute-mobile.png",
    fullPage: true,
  });
});
