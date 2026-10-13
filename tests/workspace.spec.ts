import { test, expect, russianStorageState } from "./fixtures";

test("two independent clients share bindings, topology, playback and persistence", async ({
  browser,
  request,
}) => {
  const original = await (
    await request.get("http://127.0.0.1:8010/api/project")
  ).json();
  const context = await browser.newContext({ storageState: russianStorageState });
  const env = await context.newPage(),
    editor = await context.newPage();
  const errors: string[] = [];
  env.on("pageerror", (e) => errors.push(e.message));
  editor.on("pageerror", (e) => errors.push(e.message));
  try {
    await env.goto("http://127.0.0.1:5183");
    await editor.goto("http://127.0.0.1:5184");
    await expect(env.getByText("Синхронизировано")).toBeVisible();
    await expect(editor.getByText("Синхронизировано")).toBeVisible();
    await env.getByRole("button", { name: "Нейроны", exact: true }).click();
    await env.locator("#b-forward").selectOption("explore");
    await env.getByRole("button", { name: "Сохранить назначения" }).click();
    await editor.getByRole("button", { name: "Нейроны", exact: true }).click();
    await editor.getByPlaceholder("Поиск по ID или имени").fill("explore");
    await editor.locator('[data-id="explore"]').click();
    await expect(editor.getByText("Вперёд →")).toBeVisible();
    await editor
      .getByRole("button", { name: "Генератор", exact: true })
      .click();
    await editor.locator('[name="count"]').fill("12");
    await editor.locator('[name="label"]').fill("E2E ganglion");
    await editor.getByRole("button", { name: "Сгенерировать ганглий" }).click();
    await expect(editor.locator("#chart-group option")).toHaveCount(2);
    await expect(env.locator("#chart-group option")).toHaveCount(2);
    await env.getByRole("button", { name: "▶ Запустить", exact: true }).click();
    await expect(
      editor.getByRole("button", { name: "Ⅱ Пауза", exact: true }),
    ).toBeVisible();
    await editor.getByRole("button", { name: "Ⅱ Пауза", exact: true }).click();
    await expect(
      env.getByRole("button", { name: "▶ Запустить", exact: true }),
    ).toBeVisible();
    await env.getByRole("button", { name: "Мир", exact: true }).click();
    await env
      .getByRole("button", { name: "Сгенерировать лабиринт", exact: true })
      .click();
    await expect(
      env.getByText("Лабиринт создан", { exact: true }),
    ).toBeVisible();
    const state = await (
      await request.get("http://127.0.0.1:8010/api/state")
    ).json();
    expect(
      state.world.objects.filter((o: any) => o.kind === "obstacle").length,
    ).toBeGreaterThan(20);
    await editor
      .getByRole("button", { name: "Сохранить", exact: true })
      .click();
    const exported = await (
      await request.get("http://127.0.0.1:8010/api/export")
    ).json();
    expect(exported.topology.ganglia[0].members.length).toBe(12);
    expect(exported.bindings.forward).toBe("explore");
    await env.screenshot({
      path: "test-results/environment-desktop.png",
      fullPage: true,
    });
    await editor.getByRole("button", { name: "Вписать всё" }).click();
    await editor.screenshot({
      path: "test-results/editor-desktop.png",
      fullPage: true,
    });
    expect(errors).toEqual([]);
  } finally {
    const p = await (
      await request.get("http://127.0.0.1:8010/api/project")
    ).json();
    await request.post("http://127.0.0.1:8010/api/command", {
      data: { action: "import", data: original, revision: p.revision },
    });
    await context.close();
  }
});

test("mobile keeps controls accessible without horizontal overflow", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("http://127.0.0.1:5183");
  await expect(page.getByText("Синхронизировано")).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBeTruthy();
  await page.screenshot({
    path: "test-results/environment-mobile.png",
    fullPage: true,
  });
  await page.goto("http://127.0.0.1:5184");
  await expect(page.getByText("Синхронизировано")).toBeVisible();
  await page.getByRole("button", { name: "Генератор", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "Сгенерировать ганглий" }),
  ).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBeTruthy();
  await page.screenshot({
    path: "test-results/editor-mobile.png",
    fullPage: true,
  });
});

test("canvas neuron creation, editing, connecting and world form submission", async ({
  page,
  request,
}) => {
  const api = "http://127.0.0.1:8010";
  const original = await (await request.get(api + "/api/project")).json();
  const project = async () =>
    await (await request.get(api + "/api/project")).json();
  try {
    await page.goto("http://127.0.0.1:5184");
    await expect(page.getByText("Синхронизировано")).toBeVisible();
    await page
      .getByRole("button", { name: "Создать нейрон", exact: true })
      .click();
    const canvas = page.locator("#scene");
    const box = (await canvas.boundingBox())!;
    await canvas.click({
      position: { x: box.width * 0.65, y: box.height * 0.7 },
    });
    await expect(page.locator("#neuron-form")).toBeVisible();
    expect(
      await page
        .locator("#neuron-form")
        .evaluate((el: HTMLFormElement) => el.checkValidity()),
    ).toBeTruthy();
    await page.locator('[name="label"]').fill("E2E neuron");
    await page.locator('[name="bias"]').fill("0.2");
    await page
      .getByRole("button", { name: "Применить параметры", exact: true })
      .click();
    await expect
      .poll(
        async () =>
          (await project()).topology.neurons.find(
            (n: any) => n.label === "E2E neuron",
          )?.reset_mode,
      )
      .toBe("retain");
    await page.getByRole("button", { name: "Связать ↗", exact: true }).click();
    const current = await project();
    const target = current.topology.neurons.find(
      (n: any) => n.id === "motor_forward",
    );
    const camera = await page.evaluate(() =>
      JSON.parse(localStorage.getItem("spiking-bug.camera.editor")!),
    );
    await canvas.click({
      position: {
        x: target.x * camera.zoom + camera.x,
        y: target.y * camera.zoom + camera.y,
      },
    });
    await expect(page.locator("#synapse-form")).toBeVisible();
    await page.locator('[name="kind"]').selectOption("mod_exc");
    await page.locator('[name="weight"]').fill("-0.5");
    await page
      .getByRole("button", { name: "Создать связь", exact: true })
      .click();
    await expect
      .poll(async () =>
        (await project()).topology.synapses.some(
          (s: any) =>
            s.target === "motor_forward" &&
            s.kind === "mod_exc" &&
            s.weight === -0.5,
        ),
      )
      .toBeTruthy();
    await page
      .getByRole("button", { name: "Удалить связь", exact: true })
      .click();
    await expect
      .poll(async () => (await project()).topology.synapses.length)
      .toBe(original.topology.synapses.length);
    expect((await project()).topology.neurons.length).toBe(
      original.topology.neurons.length + 1,
    );
    await page
      .getByRole("button", { name: "Создать рамку", exact: true })
      .click();
    const stage = (await canvas.boundingBox())!;
    await page.mouse.move(
      stage.x + stage.width * 0.25,
      stage.y + stage.height * 0.25,
    );
    await page.mouse.down();
    await page.mouse.move(
      stage.x + stage.width * 0.4,
      stage.y + stage.height * 0.45,
      { steps: 6 },
    );
    await page.mouse.up();
    await expect(page.locator("#frame-form")).toBeVisible();
    await page.locator('[name="label"]').fill("E2E frame");
    await page
      .getByRole("button", { name: "Сохранить рамку", exact: true })
      .click();
    await expect
      .poll(async () => (await project()).topology.groups.at(-1)?.label)
      .toBe("E2E frame");
    await page
      .getByRole("button", { name: "Удалить только рамку", exact: true })
      .click();
    await expect
      .poll(async () => (await project()).topology.groups.length)
      .toBe(original.topology.groups.length);
    await page.goto("http://127.0.0.1:5183");
    await expect(page.getByText("Синхронизировано")).toBeVisible();
    expect(
      await page
        .locator("#world-form")
        .evaluate((el: HTMLFormElement) => el.checkValidity()),
    ).toBeTruthy();
    await page.locator('[name="threat_mode"]').selectOption("static");
    await page
      .getByRole("button", { name: "Применить настройки", exact: true })
      .click();
    await expect
      .poll(async () => (await project()).world.config.threat_mode)
      .toBe("static");
  } finally {
    const p = await project();
    await request.post(api + "/api/command", {
      data: { action: "import", data: original, revision: p.revision },
    });
  }
});
