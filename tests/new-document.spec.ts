import { test, expect } from "./fixtures";

test("new document replaces the network, restores bindings and fits the starter neurons", async ({
  page,
  request,
}) => {
  const api = "http://127.0.0.1:8010";
  const original = await (await request.get(api + "/api/project")).json();
  try {
    await page.goto("http://127.0.0.1:5184");
    await expect(page.getByText("Синхронизировано")).toBeVisible();
    await page.locator("#new-ganglion").click();
    await page.locator('#ganglion-form [name="count"]').fill("3");
    await page.getByRole("button", { name: "Сгенерировать ганглий" }).click();
    await expect(page.locator(".live-values")).toContainText("3 нейронов");
    const before = await (await request.get(api + "/api/project")).json();
    page.once("dialog", (dialog) => dialog.dismiss());
    await page.getByRole("button", { name: "Новый документ" }).click();
    expect(
      (await (await request.get(api + "/api/project")).json()).revision,
    ).toBe(before.revision);
    // The new document must restore a useful camera after working at a distant zoom.
    await page.locator("#scene").dispatchEvent("wheel", { deltaY: 100000 });
    page.once("dialog", (dialog) => dialog.accept());
    await page.getByRole("button", { name: "Новый документ" }).click();
    await expect(page.locator("#projectname")).toHaveText(
      "Новая нервная система",
    );
    await expect(page.locator("#new-document")).toBeEnabled();
    const project = await (await request.get(api + "/api/project")).json();
    expect(project.topology.neurons).toHaveLength(17);
    expect(project.topology.ganglia).toEqual([]);
    expect(project.topology.synapses.length).toBeGreaterThan(0);
    expect(Object.keys(project.bindings)).toHaveLength(15);
    expect(project.bindings.forward).toBe("motor_forward");
    expect(project.bindings.food_left).toBe("sensor_food_left");
    expect(project.bindings.lidar_4).toBe("lidar_4");
    expect(project.world).toEqual(before.world);
    expect(
      await page.evaluate(
        () =>
          JSON.parse(localStorage.getItem("spiking-bug.camera.editor")!).zoom,
      ),
    ).toBeGreaterThan(0.05);
    await expect(
      page.getByRole("button", { name: "Запустить", exact: false }),
    ).toBeVisible();
    // Undo must not resurrect the previous document's structural edits.
    await page.locator("#scene").focus();
    await page.keyboard.press("Control+z");
    expect(
      (await (await request.get(api + "/api/project")).json()).revision,
    ).toBe(project.revision);
    await page.setViewportSize({ width: 390, height: 844 });
    await expect(page.locator("#new-document")).toBeVisible();
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= window.innerWidth,
      ),
    ).toBeTruthy();
    await page.screenshot({
      path: "test-results/new-document-mobile.png",
      fullPage: true,
    });
  } finally {
    await page.close();
    const state = await (await request.get(api + "/api/state")).json();
    const response = await request.post(api + "/api/command", {
      data: { action: "import", data: original, revision: state.revision },
    });
    expect(response.ok()).toBeTruthy();
  }
});
