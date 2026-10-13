import { test, expect, type Page } from "@playwright/test";

const base = "http://127.0.0.1:";
const key = "spiking-bug.language";

async function expectEnglishUI(page: Page) {
  // Language names and user-authored project data are intentionally not translated.
  const untranslated = await page.evaluate(() => {
    const nodes = document.querySelectorAll(
      "button, h1, h3, p.help, .heading p, .side-tabs, .legend, .metric label, label, #stage-hint, #stats, #performance, #rate, dialog p",
    );
    return [...nodes]
      .filter(
        (el) => !el.hasAttribute("data-id") && !el.hasAttribute("data-edge"),
      )
      .map((el) => el.textContent ?? "")
      .filter((text) => /[А-Яа-яЁё]/.test(text));
  });
  expect(untranslated).toEqual([]);
}

for (const [port, heading, russianHeading] of [
  [5183, "Living environment", "Живая среда"],
  [5184, "Connectome editor", "Редактор коннектома"],
] as const) {
  test(`${port}: English default, translated panels, persisted language and mobile selector`, async ({
    page,
    request,
  }) => {
    const errors: string[] = [];
    page.on("pageerror", (error) => errors.push(error.message));
    await page.goto(base + port);
    await expect(page.locator("#connection")).toHaveText("Synchronized");
    await expect(page.locator("html")).toHaveAttribute("lang", "en");
    await expect(
      page.getByRole("heading", { name: heading, exact: true }),
    ).toBeVisible();
    await expect(page.getByLabel("Language", { exact: true })).toHaveValue(
      "en",
    );
    await expectEnglishUI(page);
    if (port === 5183) {
      await page.getByRole("button", { name: "Bug", exact: true }).click();
      await expect(page.getByLabel("Recovery / s")).toBeVisible();
      await expectEnglishUI(page);
      await page.getByRole("button", { name: "Neurons", exact: true }).click();
      await expect(
        page.getByRole("button", { name: "Save bindings" }),
      ).toBeVisible();
      await expectEnglishUI(page);
      await page.getByRole("button", { name: "World", exact: true }).click();
      await page.getByRole("button", { name: "Edit world JSON" }).click();
      await expect(page.getByRole("dialog")).toBeVisible();
      await expectEnglishUI(page);
      await page.getByRole("button", { name: "Cancel", exact: true }).click();
    } else {
      await page
        .getByRole("button", { name: "Generator", exact: true })
        .click();
      await expect(
        page.getByLabel("Neuron count", { exact: true }),
      ).toBeVisible();
      await expectEnglishUI(page);
      await page.getByRole("button", { name: "Neurons", exact: true }).click();
      await page.getByPlaceholder("Search by ID or name").fill("drive");
      await page.locator('[data-id="drive"]').click();
      await expect(page.getByLabel("After a spike")).toBeVisible();
      await expectEnglishUI(page);
      await page
        .getByRole("button", { name: "Connect ganglia", exact: true })
        .click();
      await expect(
        page.getByRole("combobox", { name: "Source neurons", exact: true }),
      ).toBeVisible();
      await expectEnglishUI(page);
    }
    await page.getByRole("button", { name: "Help", exact: true }).click();
    await expect(
      page.getByText("One nervous system. Two windows."),
    ).toBeVisible();
    await expectEnglishUI(page);
    await page.getByRole("button", { name: "Got it" }).click();
    const before = await (await request.get(base + "8010/api/project")).json();
    await page.getByLabel("Language", { exact: true }).selectOption("ru");
    await expect(page.locator("html")).toHaveAttribute("lang", "ru");
    await expect(
      page.getByRole("heading", { name: russianHeading, exact: true }),
    ).toBeVisible();
    expect(await page.evaluate((key) => localStorage.getItem(key), key)).toBe(
      "ru",
    );
    await page.reload();
    await expect(page.locator("#connection")).toHaveText("Синхронизировано");
    await expect(page.locator("#language")).toHaveValue("ru");
    expect(await (await request.get(base + "8010/api/project")).json()).toEqual(
      before,
    );
    await page.setViewportSize({ width: 390, height: 844 });
    await expect(page.getByLabel("Язык", { exact: true })).toBeVisible();
    for (const language of ["ru", "en"]) {
      await page.locator("#language").selectOption(language);
      await expect(page.locator("html")).toHaveAttribute("lang", language);
      expect(
        await page.evaluate(() => document.documentElement.scrollWidth),
      ).toBeLessThanOrEqual(390);
      await page.screenshot({
        path: `test-results/i18n-${port}-${language}-mobile.png`,
        fullPage: true,
      });
    }
    await page.reload();
    await expect(page.locator("#language")).toHaveValue("en");
    expect(errors).toEqual([]);
  });
}

test("invalid preference falls back to English and navigation carries Russian to the other origin", async ({
  page,
  context,
}) => {
  await page.addInitScript((key) => {
    if (!localStorage.getItem(key)) localStorage.setItem(key, "invalid");
  }, key);
  await page.goto(base + "5183");
  await expect(page.locator("#language")).toHaveValue("en");
  await page.locator("#language").selectOption("ru");
  await expect(page.locator("html")).toHaveAttribute("lang", "ru");
  const href = await page.locator(".topnav a").nth(1).getAttribute("href");
  const target = new URL(href!);
  expect(target.searchParams.get("lang")).toBe("ru");
  target.port = "5184";
  const other = await context.newPage();
  await other.goto(target.href);
  await expect(
    other.getByRole("heading", { name: "Редактор коннектома" }),
  ).toBeVisible();
  expect(await other.evaluate((key) => localStorage.getItem(key), key)).toBe(
    "ru",
  );
  expect(new URL(other.url()).searchParams.has("lang")).toBeFalsy();
});

test("English API errors keep field values and imported names intact", async ({
  page,
}) => {
  await page.route("**/api/project", async (route) => {
    const response = await route.fetch();
    const project = await response.json();
    project.name = "Мой жук <test>";
    await route.fulfill({ json: project });
  });
  let error = "width: диапазон 400…12000";
  await page.route("**/api/command", (route) =>
    route.fulfill({
      status: 400,
      contentType: "application/json",
      body: JSON.stringify({ error }),
    }),
  );
  await page.goto(base + "5183");
  await expect(page.locator("#connection")).toHaveText("Synchronized");
  await page
    .getByRole("button", { name: "Apply settings", exact: true })
    .click();
  await expect(page.locator("#toast")).toHaveText("width: range 400…12000");
  await expect(page.locator("#projectname")).toHaveText("Мой жук <test>");
  error = "Нейрон не найден: знак связи противоречит полярности нейрона";
  await page
    .getByRole("button", { name: "Apply settings", exact: true })
    .click();
  await expect(page.locator("#toast")).toHaveText(
    "Нейрон не найден: connection sign conflicts with neuron polarity",
  );
  error =
    "Устройство cuda недоступно; выбран CPU. Неизвестное вычислительное устройство";
  await page
    .getByRole("button", { name: "Apply settings", exact: true })
    .click();
  await expect(page.locator("#toast")).toHaveText(
    "Device cuda is unavailable; using CPU. Unknown compute device",
  );
});
