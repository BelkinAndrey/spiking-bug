import { test, expect } from "@playwright/test";
const api = "http://127.0.0.1:8010";
const getProject = async (request: any) =>
  (await request.get(api + "/api/project")).json();
const cmd = async (request: any, action: string, data: unknown = {}) => {
  const p = await getProject(request);
  const res = await request.post(api + "/api/command", {
    data: { action, data, revision: p.revision },
  });
  expect(res.ok()).toBeTruthy();
  return res.json();
};
function fixture() {
  return {
    version: 1,
    name: "Interaction fixture",
    topology: {
      format_version: 3,
      task: "BUG",
      neurons: ["a", "b"].flatMap((g, k) =>
        [0, 1, 2, 3].map((i) => ({
          id: g + i,
          label: g + i,
          x: 200 + k * 450 + (i % 2) * 60 - 30,
          y: 250 + Math.floor(i / 2) * 60 - 30,
        })),
      ),
      synapses: [],
      ganglia: ["a", "b"].map((g, k) => ({
        id: g,
        label: g,
        x: 200 + k * 450,
        y: 250,
        radius: 100,
        members: [0, 1, 2, 3].map((i) => g + i),
      })),
    },
    bindings: {},
    world: {
      config: { width: 1200, height: 1000, food_target: 0, threat_target: 0 },
      spawn: { x: 600, y: 500, heading: 0 },
      objects: [],
      zones: [],
    },
  };
}

test("arrow keys and physical WASD move and release while paused without bindings", async ({
  page,
  request,
}) => {
  const original = await getProject(request);
  try {
    await cmd(request, "import", fixture());
    await page.goto("http://127.0.0.1:5183");
    await expect(page.getByText("Синхронизировано")).toBeVisible();
    const state = async () => (await request.get(api + "/api/state")).json();
    const x = (await state()).world.agent.x;
    await page.locator("#scene").focus();
    await page.keyboard.down("ArrowUp");
    await expect
      .poll(async () => (await state()).world.agent.x)
      .toBeGreaterThan(x + 3);
    await page.keyboard.up("ArrowUp");
    await expect
      .poll(async () => {
        const a = (await state()).world.agent.x;
        await page.waitForTimeout(120);
        return (await state()).world.agent.x - a;
      })
      .toBe(0);
    const released = (await state()).world.agent.x;
    await page.keyboard.down("KeyW");
    await expect
      .poll(async () => (await state()).world.agent.x)
      .toBeGreaterThan(released + 3);
    await page.keyboard.up("KeyW");
    expect((await state()).running).toBe(false);
    expect((await state()).t).toBe(0);
    await page.locator('[name="width"]').focus();
    const held = (await state()).world.agent.x;
    await page.keyboard.press("ArrowUp");
    await page.waitForTimeout(400);
    expect((await state()).world.agent.x).toBe(held);
  } finally {
    await cmd(request, "manual", {});
    await cmd(request, "import", original);
  }
});

test("fullscreen, chart toggle, whole-ganglion dragging and both connection previews", async ({
  page,
  request,
}) => {
  const original = await getProject(request);
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  try {
    await cmd(request, "import", fixture());
    await page.goto("http://127.0.0.1:5184");
    await expect(page.getByText("Синхронизировано")).toBeVisible();
    await page
      .getByRole("button", { name: "Скрыть график", exact: true })
      .click();
    await expect(page.locator(".chart-wrap")).toBeHidden();
    await page
      .getByRole("button", { name: "Показать график", exact: true })
      .click();
    await expect(page.locator(".chart-wrap")).toBeVisible();
    await page
      .getByRole("button", { name: "Полноэкранный режим", exact: true })
      .click();
    await expect(page.locator(".layout")).toHaveClass(/editor-fullscreen/);
    await expect(page.locator(".chart-wrap")).toBeHidden();
    await page
      .getByRole("button", {
        name: "Выйти из полноэкранного режима",
        exact: true,
      })
      .click();
    await expect(page.locator(".layout")).not.toHaveClass(/editor-fullscreen/);
    await page
      .getByRole("button", { name: "Вписать всё", exact: true })
      .click();
    const camera = await page.evaluate(() =>
      JSON.parse(localStorage.getItem("spiking-bug.camera.editor")!),
    );
    const canvas = page.locator("#scene");
    const bounds = (await canvas.boundingBox())!;
    const point = (x: number, y: number) => ({
      x: bounds.x + x * camera.zoom + camera.x,
      y: bounds.y + y * camera.zoom + camera.y,
    });
    const start = point(328, 250);
    await page.mouse.move(start.x, start.y);
    await page.mouse.down();
    await page.mouse.move(start.x + 45, start.y + 25, { steps: 8 });
    await page.mouse.up();
    await expect
      .poll(async () => (await getProject(request)).topology.ganglia[0].x)
      .toBeCloseTo(200 + 45 / camera.zoom);
    const moved = await getProject(request);
    for (let i = 0; i < 4; i++) {
      expect(
        moved.topology.neurons[i].x - fixture().topology.neurons[i].x,
      ).toBeCloseTo(45 / camera.zoom);
      expect(
        moved.topology.neurons[i].y - fixture().topology.neurons[i].y,
      ).toBeCloseTo(25 / camera.zoom);
    }
    expect(moved.topology.neurons[4].x).toBe(620);
    await page
      .getByRole("button", { name: "Создать синапс", exact: true })
      .click();
    const src = moved.topology.neurons[0],
      dst = moved.topology.neurons[4];
    await page.mouse.click(point(src.x, src.y).x, point(src.x, src.y).y);
    await page.mouse.click(point(dst.x, dst.y).x, point(dst.x, dst.y).y);
    await expect(page.locator("#scene")).toHaveAttribute(
      "data-pending-target",
      "b0",
    );
    await expect(page.locator("#stage-hint")).toContainText("Намечена связь");
    expect((await getProject(request)).topology.synapses).toHaveLength(0);
    await page.screenshot({ path: "test-results/pending-synapse.png" });
    await page
      .getByRole("button", { name: "Создать связь", exact: true })
      .click();
    await expect
      .poll(async () => (await getProject(request)).topology.synapses.length)
      .toBe(1);
    await expect(canvas).toHaveAttribute("data-pending-target", "");
    await page
      .getByRole("button", { name: "Связать ганглии", exact: true })
      .click();
    const ga = moved.topology.ganglia[0],
      gb = moved.topology.ganglia[1];
    await page.mouse.click(
      point(ga.x + 128, ga.y).x,
      point(ga.x + 128, ga.y).y,
    );
    await page.mouse.click(
      point(gb.x + 128, gb.y).x,
      point(gb.x + 128, gb.y).y,
    );
    await expect(page.locator('#projection-form [name="source"]')).toHaveValue(
      "a",
    );
    await expect(page.locator('#projection-form [name="target"]')).toHaveValue(
      "b",
    );
    await page.locator('[name="density"]').fill("1");
    await page.locator('[name="kind"]').selectOption("mod_inh");
    await page.locator('[name="weight"]').fill("-.4");
    await page
      .getByRole("button", { name: "Сгенерировать связи", exact: true })
      .click();
    await expect
      .poll(
        async () =>
          (await getProject(request)).topology.synapses.filter(
            (s: any) => s.kind === "mod_inh",
          ).length,
      )
      .toBe(16);
    await page
      .getByRole("button", { name: "Выбрать / переместить", exact: true })
      .click();
    await page.getByRole("button", { name: "Генератор", exact: true }).click();
    await page.locator('[name="count"]').fill("12");
    await page.locator('[name="density"]').fill("1");
    await page.locator('[name="max_distance"]').fill("1");
    await page
      .getByRole("button", { name: "Сгенерировать ганглий", exact: true })
      .click();
    await expect
      .poll(async () => (await getProject(request)).topology.ganglia.length)
      .toBe(3);
    const final = await getProject(request),
      ids = final.topology.ganglia[2].members;
    expect(
      final.topology.synapses.filter((s: any) => ids.includes(s.source)),
    ).toHaveLength(0);
    expect(errors).toEqual([]);
  } finally {
    await cmd(request, "import", original);
  }
});
