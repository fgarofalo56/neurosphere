import type { Locator, Page } from "@playwright/test";
import { MOCK_API_URL, expect, test } from "../../e2e-support/fixtures.ts";
import { DOMAIN_OK, INTENT_EXPIRED } from "../../mock-api/server.ts";
import { seedPreferences } from "./axe-support.ts";
import { Recorder, focusedLabel, tabUntil, writePrecheckAggregate } from "./precheck-support.ts";

// PRP-24 item 3b: one test per row of docs/accessibility/keyboard-checklist.md "Key flows", driven
// with real keys (page.keyboard). This is an automated PRE-CHECK; a human tester still confirms and
// signs the checklist. Every assertion here is honest: a product defect fails the test.

const SCOPE = "keyboard-flow";
const DOMAIN = encodeURIComponent(DOMAIN_OK);

test.afterAll(() => {
  writePrecheckAggregate();
});

/** True when the focused element is, or sits inside, the given selector. */
const focusIn = (page: Page, selector: string): Promise<boolean> =>
  page.evaluate((s) => document.activeElement?.closest(s) != null, selector);

/** Moves focus with arrow keys until the focused element has the given role and name. */
async function arrowTo(
  page: Page,
  role: string,
  name: string,
  key = "ArrowDown",
  limit = 10,
): Promise<void> {
  for (let i = 0; i < limit; i += 1) {
    const hit = await page.evaluate(
      ([r, n]) => {
        const el = document.activeElement;
        return el?.getAttribute("role") === r && (el.textContent ?? "").trim() === n;
      },
      [role, name] as const,
    );
    if (hit) return;
    await page.keyboard.press(key);
  }
  throw new Error(
    `arrow keys never reached ${role} "${name}"; focus is on ${await focusedLabel(page)}`,
  );
}

async function storedTheme(page: Page): Promise<{ packId?: string; themeName?: string }> {
  return page.evaluate(() => JSON.parse(window.localStorage.getItem("ns.theme") ?? "{}"));
}

async function openAccountMenu(page: Page, key: "Enter" | "Space"): Promise<Locator> {
  const trigger = page.getByRole("button", { name: /^Account:/ });
  await trigger.focus();
  await page.keyboard.press(key);
  const menu = page.getByRole("menu");
  await expect(menu).toBeVisible();
  return menu;
}

test("skip link: first Tab stop, Enter moves focus into main", async ({ page }) => {
  const r = new Recorder(SCOPE, "skip-link");
  await page.goto(`/?domain_id=${DOMAIN}`);
  await expect(page.getByRole("main")).toBeVisible();
  await page.keyboard.press("Tab");
  const skip = page.getByRole("link", { name: "Skip to main content" });
  await r.check("skip link is the first Tab stop", () => expect(skip).toBeFocused());
  await r.check("skip link becomes visible on focus", async () => {
    const box = await skip.boundingBox();
    expect(box?.y ?? -1000).toBeGreaterThanOrEqual(0);
  });
  await page.keyboard.press("Enter");
  await r.check("Enter moves focus to the main landmark", () =>
    expect(page.getByRole("main")).toBeFocused(),
  );
  await r.check("the next Tab stays inside or after main (not back to the skip link)", async () => {
    await page.keyboard.press("Tab");
    expect(await focusIn(page, "a[href='#main-content']")).toBe(false);
  });
  r.finish();
});

test("primary navigation: reachable by Tab, activates with Enter, current page indicated", async ({
  page,
}) => {
  const r = new Recorder(SCOPE, "primary-navigation");
  await page.goto(`/?domain_id=${DOMAIN}`);
  const nav = page.getByRole("navigation", { name: "Primary" });
  await expect(nav).toBeVisible();
  await r.must("a navigation link is reachable by Tab", () =>
    tabUntil(page, () =>
      page.evaluate(() => document.activeElement?.closest("[aria-label='Primary']") != null),
    ),
  );
  await r.check("every nav group has a labelled group", async () => {
    await expect(nav.getByRole("group")).not.toHaveCount(0);
  });
  await r.must("Tab reaches the Cost dashboard link", () =>
    tabUntil(page, () =>
      page.evaluate(() => document.activeElement?.textContent?.trim() === "Cost dashboard"),
    ),
  );
  await page.keyboard.press("Enter");
  await r.check("Enter activates the link (client-side navigation)", () =>
    expect(page).toHaveURL(/\/dashboards\/cost\?/),
  );
  await r.check("the current page is indicated with aria-current", () =>
    expect(nav.getByRole("link", { name: "Cost dashboard", exact: true })).toHaveAttribute(
      "aria-current",
      "page",
    ),
  );
  r.finish();
});

test("user menu: theme mode is selectable by keys, Escape closes and returns focus, persists", async ({
  page,
}) => {
  const r = new Recorder(SCOPE, "user-menu-theme-mode");
  await seedPreferences(page, { mode: "light" });
  await page.goto(`/?domain_id=${DOMAIN}`);
  const trigger = page.getByRole("button", { name: /^Account:/ });
  await expect(trigger).toBeVisible();

  await r.must("the account trigger is reachable by Tab", () =>
    tabUntil(page, () =>
      page.evaluate(() => document.activeElement?.textContent?.startsWith("Account:") ?? false),
    ),
  );
  await page.keyboard.press("Enter");
  await r.must("Enter opens the menu", () => expect(page.getByRole("menu")).toBeVisible());
  await r.check("focus moves into the menu", async () => {
    expect(await focusIn(page, "[role='menu']")).toBe(true);
  });
  await arrowTo(page, "menuitemradio", "Dark");
  await page.keyboard.press("Enter");
  await r.check("Enter on Dark selects it (persisted)", () =>
    expect.poll(async () => (await storedTheme(page)).themeName).toBe("dark"),
  );

  // Selecting a radio may or may not close the menu; reopen only when it did.
  await page.waitForTimeout(150);
  if ((await page.getByRole("menu").count()) === 0) await openAccountMenu(page, "Space");
  await arrowTo(page, "menuitemradio", "High contrast");
  await page.keyboard.press("Space");
  await r.check("Space on High contrast selects it (persisted)", () =>
    expect.poll(async () => (await storedTheme(page)).themeName).toBe("high-contrast"),
  );

  await page.waitForTimeout(150);
  if ((await page.getByRole("menu").count()) === 0) await openAccountMenu(page, "Enter");
  await arrowTo(page, "menuitemradio", "Light", "ArrowUp");
  await page.keyboard.press("Enter");
  await r.check("Light can be selected back", () =>
    expect.poll(async () => (await storedTheme(page)).themeName).toBe("light"),
  );

  await page.waitForTimeout(150);
  if ((await page.getByRole("menu").count()) === 0) await openAccountMenu(page, "Space");
  await page.keyboard.press("Escape");
  await r.check("Escape closes the menu", () => expect(page.getByRole("menu")).toHaveCount(0));
  await r.check("focus returns to the Account trigger", () => expect(trigger).toBeFocused());
  r.finish();
});

test("user menu: theme pack is selectable by keys and persists after reload", async ({ page }) => {
  const r = new Recorder(SCOPE, "user-menu-theme-pack");
  // No seeded preference: an init script would re-seed on reload and defeat the persistence check.
  await page.goto(`/?domain_id=${DOMAIN}`);
  const trigger = page.getByRole("button", { name: /^Account:/ });
  await expect(trigger).toBeVisible();

  await openAccountMenu(page, "Space");
  await r.check("Space opens the menu", () => expect(page.getByRole("menu")).toBeVisible());
  await r.check("pack names are menuitemradio items", async () => {
    await expect(page.getByRole("menuitemradio", { name: "Neutral" })).toBeVisible();
    await expect(page.getByRole("menuitemradio", { name: "Sample Agency" })).toBeVisible();
  });
  await arrowTo(page, "menuitemradio", "Sample Agency");
  await page.keyboard.press("Enter");
  await r.check("Enter on Sample Agency selects it (persisted)", () =>
    expect.poll(async () => (await storedTheme(page)).packId).toBe("sample-agency"),
  );
  await page.waitForTimeout(150);
  if ((await page.getByRole("menu").count()) > 0) await page.keyboard.press("Escape");
  await r.check("focus returns to the Account trigger after the choice", () =>
    expect(trigger).toBeFocused(),
  );

  await page.reload();
  await expect(trigger).toBeVisible();
  await r.check("the pack persists after reload (stored and shown as checked)", async () => {
    expect((await storedTheme(page)).packId).toBe("sample-agency");
    await openAccountMenu(page, "Enter");
    await expect(page.getByRole("menuitemradio", { name: "Sample Agency" })).toBeChecked();
    await page.keyboard.press("Escape");
  });
  await r.check("Escape closes the menu and returns focus to the trigger", async () => {
    await expect(page.getByRole("menu")).toHaveCount(0);
    await expect(trigger).toBeFocused();
  });
  r.finish();
});

test("sandbox toggle: Space switches it on, state exposed, focus stays; banner is not a trap", async ({
  page,
}) => {
  const r = new Recorder(SCOPE, "sandbox-toggle");
  const rb = new Recorder(SCOPE, "sandbox-banner");
  await seedPreferences(page, { mode: "light" });
  await page.goto(`/?domain_id=${DOMAIN}`);
  const toggle = page.getByRole("switch", { name: "Sandbox mode" });
  await r.must("the switch is reachable by Tab", async () => {
    await tabUntil(page, () => toggle.evaluate((el) => el === document.activeElement));
  });
  await r.check("switch starts unchecked", () => expect(toggle).not.toBeChecked());
  await page.keyboard.press("Space");
  await r.check("Space turns it on (aria-checked)", () => expect(toggle).toBeChecked());
  await r.check("focus stays on the switch", () => expect(toggle).toBeFocused());
  const banner = page.getByRole("region", { name: "Sandbox mode: synthetic data only" });
  await r.check("the banner appears", () => expect(banner).toBeVisible());
  await r.check("focus still on the switch after the banner appeared", () =>
    expect(toggle).toBeFocused(),
  );

  await rb.check("banner is a labelled region before main in reading order", async () => {
    const before = await banner.evaluate((el) => {
      const main = document.querySelector("main");
      return (
        main !== null &&
        Boolean(el.compareDocumentPosition(main) & Node.DOCUMENT_POSITION_FOLLOWING)
      );
    });
    expect(before).toBe(true);
  });
  await rb.check("banner holds no focusable control (cannot trap)", async () => {
    const focusable = await banner
      .locator("a[href],button,input,select,textarea,[tabindex]")
      .count();
    expect(focusable).toBe(0);
  });
  await rb.check("Tab moves on from the switch (not stuck)", async () => {
    const before = await focusedLabel(page);
    await page.keyboard.press("Tab");
    expect(await focusedLabel(page)).not.toBe(before);
  });
  await page.keyboard.press("Shift+Tab");
  await r.check("Space turns it off again", async () => {
    await toggle.focus();
    await page.keyboard.press("Space");
    await expect(toggle).not.toBeChecked();
    await expect(banner).toHaveCount(0);
  });
  r.finish();
  rb.finish();
});

test("map table (treegrid): single Tab stop, arrows, Enter, Home/End, Tab leaves", async ({
  page,
}) => {
  const r = new Recorder(SCOPE, "map-table-treegrid");
  await seedPreferences(page, { mode: "light" });
  await page.goto(`/map/table?domain_id=${DOMAIN}`);
  const grid = page.getByRole("treegrid", { name: "Map nodes" });
  await expect(grid).toBeVisible();
  const label = (): Promise<string | null> =>
    page.evaluate(
      () =>
        document.activeElement?.closest("tr[data-row-key]")?.querySelector("[data-testid='label']")
          ?.textContent ?? null,
    );
  await r.must("Tab reaches a grid row", () =>
    tabUntil(page, () =>
      page.evaluate(() => document.activeElement?.matches("tr[data-row-key]") ?? false),
    ),
  );
  await r.check("roving tabindex: exactly one row is a Tab stop", () =>
    expect(grid.locator("tr[data-row-key][tabindex='0']")).toHaveCount(1),
  );
  const first = await label();
  await page.keyboard.press("ArrowDown");
  await r.check("ArrowDown moves to the next row", async () => {
    expect(await label()).not.toBe(first);
  });
  await page.keyboard.press("ArrowUp");
  await r.check("ArrowUp moves back", async () => {
    expect(await label()).toBe(first);
  });
  await page.keyboard.press("End");
  const last = await label();
  await r.check("End moves to the last row", async () => {
    expect(last).not.toBe(first);
  });
  await page.keyboard.press("Home");
  await r.check("Home returns to the first row", async () => {
    expect(await label()).toBe(first);
  });
  const row = grid.locator("tr[data-row-key]").first();
  await page.keyboard.press("Enter");
  await r.check("Enter expands the focused cluster row", () =>
    expect(row).toHaveAttribute("aria-expanded", "true"),
  );
  await r.check("focus stays on the row after expanding", () => expect(row).toBeFocused());
  await r.check("Tab leaves the grid", () =>
    tabUntil(page, () =>
      page.evaluate(() => !document.activeElement?.closest("[role='treegrid']")),
    ),
  );
  r.finish();
});

test("map page: 'View as table' reachable, reduced-motion switch works from the keyboard", async ({
  page,
}) => {
  const r = new Recorder(SCOPE, "map-page-webgl");
  await seedPreferences(page, { mode: "light" });
  await page.goto(`/map?domain_id=${DOMAIN}`);
  await expect(
    page.locator("[data-testid='map-canvas'][data-node-count]:not([data-node-count='0'])"),
  ).toBeVisible({ timeout: 30_000 });
  const link = page.getByRole("link", { name: "View as table" });
  await r.must("'View as table' link is reachable by Tab", () =>
    tabUntil(page, () => link.evaluate((el) => el === document.activeElement), 120),
  );
  await page.keyboard.press("Tab");
  const motion = page.getByRole("switch", { name: /reduce motion/i });
  await r.check("the reduce-motion switch is the next Tab stop", () =>
    expect(motion).toBeFocused(),
  );
  await page.keyboard.press("Space");
  await r.check("Space turns reduced motion on", () => expect(motion).toBeChecked());
  await r.check("animation switches off (data-edge-animation=off)", () =>
    expect(page.getByTestId("map-canvas")).toHaveAttribute("data-edge-animation", "off"),
  );
  await link.focus();
  await page.keyboard.press("Enter");
  await r.check("Enter on 'View as table' opens the table view", () =>
    expect(page.getByRole("treegrid", { name: "Map nodes" })).toBeVisible(),
  );
  r.finish();
});

test("chart: Chart/Table tabs by arrow keys, table outside the iframe, no trap in the frame", async ({
  page,
}) => {
  const r = new Recorder(SCOPE, "chart-iframe");
  await seedPreferences(page, { mode: "light" });
  await page.goto("/src/features/charts/harness/index.html?plan=bar");
  await expect
    .poll(
      () =>
        page.evaluate(
          () => (window as unknown as { __chart?: { status: string } }).__chart?.status ?? "none",
        ),
      { timeout: 30_000 },
    )
    .toBe("rendered");
  const chartTab = page.getByRole("tab", { name: "Chart" });
  const tableTab = page.getByRole("tab", { name: "Table" });
  await r.must("the Chart tab is reachable by Tab", () =>
    tabUntil(page, () => chartTab.evaluate((el) => el === document.activeElement), 20),
  );
  await r.check("Chart tab is selected initially", () =>
    expect(chartTab).toHaveAttribute("aria-selected", "true"),
  );
  // Fluent's TabList uses manual activation (WAI-ARIA tabs pattern): arrows move focus, Enter or
  // Space selects.
  await page.keyboard.press("ArrowRight");
  await r.check("ArrowRight moves focus to the Table tab", () => expect(tableTab).toBeFocused());
  await page.keyboard.press("Enter");
  await r.check("Enter selects the Table tab", () =>
    expect(tableTab).toHaveAttribute("aria-selected", "true"),
  );
  await r.check(
    "the data table is in the host document, reached without entering the iframe",
    async () => {
      const table = page.getByRole("table", { name: "Cost by month" });
      await expect(table).toBeVisible();
      expect(
        await table.evaluate((el) => !el.closest("iframe") && el.ownerDocument === document),
      ).toBe(true);
      expect(await focusIn(page, "iframe")).toBe(false);
    },
  );
  await page.keyboard.press("ArrowLeft");
  await r.check("ArrowLeft moves focus back to the Chart tab", () =>
    expect(chartTab).toBeFocused(),
  );
  await page.keyboard.press("Space");
  await r.check("Space selects the Chart tab", () =>
    expect(chartTab).toHaveAttribute("aria-selected", "true"),
  );
  await r.check("Tab never traps focus in or around the frame", async () => {
    const seen: string[] = [];
    for (let i = 0; i < 8; i += 1) {
      await page.keyboard.press("Tab");
      seen.push(await focusedLabel(page));
    }
    const runs = seen.filter((s, i) => i > 1 && s === seen[i - 1] && s === seen[i - 2]);
    expect(runs, `focus stuck on: ${seen.join(" > ")}`).toEqual([]);
  });
  r.finish();
});

test("reports: list and view operable, share dialog traps focus and restores it", async ({
  page,
}) => {
  const r = new Recorder(SCOPE, "reports");
  await seedPreferences(page, { mode: "light" });
  await page.goto(`/reports?domain_id=${DOMAIN}`);
  const list = page.getByRole("table", { name: "Saved reports" });
  await expect(list).toBeVisible();
  const firstLink = list.getByRole("link").first();
  await r.must("a report link in the list is reachable by Tab", () =>
    tabUntil(page, () => firstLink.evaluate((el) => el === document.activeElement), 120),
  );
  await page.keyboard.press("Enter");
  await r.check("Enter opens the report view", () => expect(page).toHaveURL(/\/reports\/view\?/));
  await expect(page.getByTestId("run-section")).toBeVisible();

  const run = page.getByRole("button", { name: "Run again" });
  await r.check("Run again is operable with Enter", async () => {
    await run.focus();
    const rerun = page.waitForResponse((res) => res.url().includes("/run"));
    await page.keyboard.press("Enter");
    expect((await rerun).status()).toBeLessThan(400);
  });

  const share = page.getByRole("button", { name: "Share", exact: true });
  await share.focus();
  await page.keyboard.press("Enter");
  const dialog = page.getByRole("dialog", { name: "Share report" });
  await r.must("Enter opens the Share dialog", () => expect(dialog).toBeVisible());
  await r.check("focus moves into the dialog", async () => {
    expect(await focusIn(page, "[role='dialog']")).toBe(true);
  });
  await r.check("focus stays inside the dialog for 12 Tab and 3 Shift+Tab presses", async () => {
    const outside: string[] = [];
    for (let i = 0; i < 15; i += 1) {
      await page.keyboard.press(i < 12 ? "Tab" : "Shift+Tab");
      if (!(await focusIn(page, "[role='dialog']"))) outside.push(await focusedLabel(page));
    }
    expect(outside, `focus left the dialog: ${outside.join(", ")}`).toEqual([]);
  });
  await r.check("the share form is operable (field then Share button)", async () => {
    const field = dialog.getByLabel("Person (principal id)");
    await field.focus();
    await page.keyboard.type("commercial:e2e:entra:person:psn_precheck");
    await expect(field).toHaveValue("commercial:e2e:entra:person:psn_precheck");
    await field.fill("");
  });
  await page.keyboard.press("Escape");
  await r.check("Escape closes the dialog", () => expect(dialog).toHaveCount(0));
  await r.check("focus is restored to the Share trigger", () => expect(share).toBeFocused());
  r.note(
    "save-as-report dialog",
    "The 'Save as report' dialog is offered only when the copilot chart event carries a query spec; the mock API fixtures never send one, so its keyboard behaviour is NOT AUTOMATABLE here.",
  );
  r.finish();
});

test("copilot panel: opens and closes by keyboard, answers reachable, focus managed", async ({
  page,
}) => {
  const r = new Recorder(SCOPE, "copilot-panel");
  await seedPreferences(page, { mode: "light" });
  await page.goto(`/?domain_id=${DOMAIN}`);
  const toggle = page.getByRole("button", { name: "Open assistant" });
  await expect(toggle).toBeVisible();
  await r.must("the toggle is reachable by Tab", () =>
    tabUntil(page, () => toggle.evaluate((el) => el === document.activeElement), 120),
  );
  await page.keyboard.press("Enter");
  const panel = page.getByRole("region", { name: "Assistant" });
  await r.must("Enter opens the panel", () => expect(panel).toBeVisible());
  const input = page.getByRole("textbox", { name: "Ask the assistant" });
  await r.check("focus moves to the input", () => expect(input).toBeFocused());
  await page.keyboard.type("fixture:answered how much did we spend?");
  await page.keyboard.press("Enter");
  const turn = page.getByTestId("assistant-turn");
  await r.check("Enter sends and an answer arrives", () =>
    expect(turn).toHaveAttribute("data-status", "answered"),
  );
  await r.check("focus is not stolen from the input when the turn arrives", () =>
    expect(input).toBeFocused(),
  );
  await r.check("the conversation log is a Tab stop (scrollable, reachable)", async () => {
    // The answer holds tabbable children (chart tabs), so the log is a few Shift+Tab stops back.
    await tabUntil(
      page,
      () => page.evaluate(() => document.activeElement?.getAttribute("role") === "log"),
      12,
      "Shift+Tab",
    );
  });
  await r.check("citations are listed in the log", () =>
    expect(page.getByTestId("citations").getByRole("listitem")).toHaveCount(3),
  );
  await input.focus();
  await page.keyboard.press("Escape");
  await r.check("Escape closes the panel", () => expect(panel).toHaveCount(0));
  await r.check("focus returns to the toggle", () =>
    expect(page.getByRole("button", { name: "Open assistant" })).toBeFocused(),
  );
  r.finish();
});

test("actions: Review and confirm dialog shows target, version, diff; Escape cancels; focus returns", async ({
  page,
  request,
}) => {
  const r = new Recorder(SCOPE, "actions-confirm-dialog");
  const reset = await request.post(`${MOCK_API_URL}/__e2e/reset/${INTENT_EXPIRED}`);
  expect(reset.status()).toBe(204);
  await seedPreferences(page, { mode: "light" });
  await page.goto(`/actions/detail?domain_id=${DOMAIN}&intent_id=${INTENT_EXPIRED}`);
  const trigger = page.getByRole("button", { name: "Review and confirm" });
  await expect(trigger).toBeVisible();
  await r.must("the trigger is reachable by Tab", () =>
    tabUntil(page, () => trigger.evaluate((el) => el === document.activeElement), 120),
  );
  await page.keyboard.press("Enter");
  const dialog = page.getByTestId("confirmation-dialog");
  await r.must("Enter opens the dialog", () => expect(dialog).toBeVisible());
  await r.check("focus moves into the dialog", async () => {
    expect(await focusIn(page, "[data-testid='confirmation-dialog']")).toBe(true);
  });
  await r.check("target, version and diff are present in the dialog", async () => {
    await expect(dialog.getByTestId("confirm-target")).not.toBeEmpty();
    await expect(dialog.getByTestId("confirm-version")).not.toBeEmpty();
    await expect(dialog.getByTestId("diff-op").first()).toBeVisible();
  });
  await r.check("Tab reaches the Cancel button and focus stays in the dialog", async () => {
    const outside: string[] = [];
    let reachedCancel = false;
    for (let i = 0; i < 8; i += 1) {
      await page.keyboard.press("Tab");
      if (!(await focusIn(page, "[data-testid='confirmation-dialog']"))) {
        outside.push(await focusedLabel(page));
      }
      if (await page.evaluate(() => document.activeElement?.textContent === "Cancel")) {
        reachedCancel = true;
      }
    }
    expect(outside, `focus left the dialog: ${outside.join(", ")}`).toEqual([]);
    expect(reachedCancel).toBe(true);
  });
  await page.keyboard.press("Escape");
  await r.check("Escape cancels (dialog closes)", () => expect(dialog).toHaveCount(0));
  await r.check("focus returns to the 'Review and confirm' trigger", () =>
    expect(trigger).toBeFocused(),
  );
  r.finish();
});
