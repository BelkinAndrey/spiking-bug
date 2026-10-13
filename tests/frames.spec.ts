import { test, expect } from "./fixtures";
import type { Topology } from "../packages/ui/types";

const api = "http://127.0.0.1:8010";
test("frames move enclosed neurons, resize independently, choose colors and undo", async ({
  page,
  request,
}) => {
  const project = async () => (await request.get(api + "/api/project")).json();
  const command = async (action: string, data: unknown) => {
    const p = await project();
    const response = await request.post(api + "/api/command", {
      data: { action, data, revision: p.revision },
    });
    expect(response.ok()).toBeTruthy();
  };
  const original = await project();
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  try {
    await command("topology", {
      neurons: [
        { id: "a", x: 200, y: 200 },
        { id: "b", x: 260, y: 260 },
        { id: "boundary", x: 100, y: 300 },
        { id: "outside", x: 450, y: 250 },
      ],
      ganglia: [{ id: "g", x: 230, y: 230, radius: 70, members: ["a", "b"] }],
      synapses: [
        { id: "s", source: "a", target: "outside", weight: 1, delay: 1 },
      ],
      groups: [
        {
          id: "f",
          label: "Frame",
          color: "#657586",
          comment: "",
          x: 100,
          y: 100,
          w: 300,
          h: 250,
        },
      ],
    });
    const initial: Topology = (await project()).topology;
    await page.addInitScript(() =>
      localStorage.setItem(
        "spiking-bug.camera.editor",
        JSON.stringify({ x: 80, y: 40, zoom: 0.9 }),
      ),
    );
    await page.goto("http://127.0.0.1:5184");
    await expect(page.getByText("Синхронизировано")).toBeVisible();
    const canvas = page.locator("#scene");
    const bounds = (await canvas.boundingBox())!;
    const camera = await page.evaluate(() =>
      JSON.parse(localStorage.getItem("spiking-bug.camera.editor")!),
    );
    const synced = async () => {
      await expect(canvas).toHaveAttribute(
        "data-revision",
        String((await project()).revision),
      );
    };
    const point = (x: number, y: number) => ({
      x: bounds.x + camera.x + x * camera.zoom,
      y: bounds.y + camera.y + y * camera.zoom,
    });
    const click = async (x: number, y: number) => {
      const p = point(x, y);
      await page.mouse.click(p.x, p.y);
    };
    const drag = async (x: number, y: number, dx: number, dy: number) => {
      await synced();
      const p = point(x, y),
        q = point(x + dx, y + dy);
      expect(p.y).toBeLessThan(bounds.y + bounds.height);
      expect(p.x).toBeLessThan(bounds.x + bounds.width);
      await page.mouse.move(p.x, p.y);
      await page.mouse.down();
      await page.mouse.move(q.x, q.y, { steps: 6 });
      await page.mouse.up();
    };
    await click(150, 112);
    const form = page.locator("#frame-form");
    await expect(form).toBeVisible();
    await expect(form.locator('input[type="number"]')).toHaveCount(0);
    await expect(form.locator('input[type="color"]')).toBeVisible();
    const stateBefore = await (await request.get(api + "/api/state")).json();
    await drag(150, 112, 60, 40);
    await expect
      .poll(async () => (await project()).topology.groups[0].x)
      .toBeCloseTo(160);
    const moved: Topology = (await project()).topology;
    for (const [i, n] of moved.neurons.entries()) {
      expect(n.x).toBeCloseTo(
        initial.neurons[i].x + (n.id === "outside" ? 0 : 60),
      );
      expect(n.y).toBeCloseTo(
        initial.neurons[i].y + (n.id === "outside" ? 0 : 40),
      );
    }
    expect(moved.ganglia[0].x).toBeCloseTo(290);
    expect(moved.synapses).toEqual(initial.synapses);
    expect((await (await request.get(api + "/api/state")).json()).session).toBe(
      stateBefore.session,
    );

    // Corners and side handles keep the opposite edge fixed and never move neurons.
    await drag(460, 390, 90, 50);
    await expect
      .poll(async () => (await project()).topology.groups[0].w)
      .toBeCloseTo(390);
    await drag(160, 290, -30, 0);
    await expect
      .poll(async () => (await project()).topology.groups[0].x)
      .toBeCloseTo(130);
    let resized: Topology = (await project()).topology;
    expect(resized.groups[0].w).toBeCloseTo(420);
    expect(resized.groups[0].h).toBeCloseTo(300);
    expect(resized.neurons).toEqual(moved.neurons);
    expect(resized.ganglia).toEqual(moved.ganglia);
    await synced();
    await page.keyboard.press("Control+z");
    await expect
      .poll(async () => (await project()).topology.groups[0].x)
      .toBeCloseTo(160);
    await synced();
    await page.keyboard.press("Control+z");
    await expect
      .poll(async () => (await project()).topology.groups[0].w)
      .toBeCloseTo(300);
    await synced();
    await page.keyboard.press("Control+z");
    await expect.poll(async () => (await project()).topology).toEqual(initial);

    // Exercise all eight resize directions with fixed opposite edges.
    for (const [x, y, dx, dy, fx, fy, w, h] of [
      [100, 100, -20, -20, 80, 80, 320, 270],
      [250, 100, 0, -20, 100, 80, 300, 270],
      [400, 100, 20, -20, 100, 80, 320, 270],
      [400, 225, 20, 0, 100, 100, 320, 250],
      [400, 350, 20, 20, 100, 100, 320, 270],
      [250, 350, 0, 20, 100, 100, 300, 270],
      [100, 350, -20, 20, 80, 100, 320, 270],
      [100, 225, -20, 0, 80, 100, 320, 250],
      [100, 225, 350, 0, 390, 100, 10, 250],
    ]) {
      await drag(x, y, dx, dy);
      await expect
        .poll(async () => {
          const f = (await project()).topology.groups[0];
          return [f.x, f.y, f.w, f.h].map(Math.round);
        })
        .toEqual([fx, fy, w, h]);
      expect((await project()).topology.neurons).toEqual(initial.neurons);
      await synced();
      await page.keyboard.press("Control+z");
      await expect
        .poll(async () => (await project()).topology)
        .toEqual(initial);
    }
    // Escape cancels both the preview and the eventual mouse-up save.
    await synced();
    const start = point(150, 112),
      end = point(180, 132);
    await page.mouse.move(start.x, start.y);
    await page.mouse.down();
    await page.mouse.move(end.x, end.y, { steps: 4 });
    await page.keyboard.press("Escape");
    await page.mouse.up();
    expect((await project()).topology).toEqual(initial);
    await click(150, 112);
    // Resize expands membership for the next move, without dragging new arrivals mid-gesture.
    await drag(400, 225, 100, 0);
    await expect
      .poll(async () => (await project()).topology.groups[0].w)
      .toBeCloseTo(400);
    await drag(150, 112, 20, 0);
    await expect
      .poll(async () => (await project()).topology.neurons[3].x)
      .toBeCloseTo(470);
    await synced();
    await form.getByRole("button", { name: "Фиолетовый", exact: true }).click();
    await expect(form.locator('input[type="color"]')).toHaveValue("#bba8ed");
    await expect(
      form.getByRole("button", { name: "Фиолетовый", exact: true }),
    ).toHaveAttribute("aria-pressed", "true");
    await form
      .getByRole("button", { name: "Сохранить рамку", exact: true })
      .click();
    await expect
      .poll(async () => (await project()).topology.groups[0].color)
      .toBe("#bba8ed");
    await synced();
    await form.locator('input[type="color"]').fill("#31a580");
    await form
      .getByRole("button", { name: "Сохранить рамку", exact: true })
      .click();
    await expect
      .poll(async () => (await project()).topology.groups[0].color)
      .toBe("#31a580");
    await page.screenshot({ path: "test-results/frame-controls.png" });
    const saved = (await project()).topology;
    await page.reload();
    await expect(page.getByText("Синхронизировано")).toBeVisible();
    await click(170, 112);
    await expect(form.locator('input[type="color"]')).toHaveValue("#31a580");
    expect((await project()).topology).toEqual(saved);
    await form
      .getByRole("button", { name: "Удалить только рамку", exact: true })
      .click();
    await expect
      .poll(async () => (await project()).topology.groups)
      .toEqual([]);
    expect((await project()).topology.neurons).toEqual(saved.neurons);
    expect(errors).toEqual([]);
  } finally {
    await page.close();
    await command("import", original);
  }
});
