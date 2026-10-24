import { MOCK_API_URL, expect, test } from "../../e2e-support/fixtures.ts";
import { DOMAIN_OK, INTENT_EXPIRED } from "../../mock-api/server.ts";
import { openSample, seedPreferences } from "./axe-support.ts";
import { Recorder, writePrecheckAggregate } from "./precheck-support.ts";
import { ROUTE_SAMPLES } from "./route-samples.ts";

// PRP-24 item 3b: for each row of docs/accessibility/screen-reader-checklist.md assert the
// accessibility-tree role, name and state that a screen reader is given (getByRole with the exact
// product names and toMatchAriaSnapshot). What a screen reader then SPEAKS depends on the AT and
// browser and is NOT AUTOMATABLE: a human tester confirms announcements and signs the checklist.
// Where the checklist wording differs from the product, the difference is recorded as a "note"
// rather than guessed at.

const SCOPE = "sr-flow";
const DOMAIN = encodeURIComponent(DOMAIN_OK);

test.afterAll(() => {
  writePrecheckAggregate();
});

test("skip link: a link named 'Skip to main content' that lands in the main landmark", async ({
  page,
}) => {
  const r = new Recorder(SCOPE, "skip-link");
  await page.goto(`/?domain_id=${DOMAIN}`);
  await expect(page.getByRole("main")).toBeVisible();
  const skip = page.getByRole("link", { name: "Skip to main content", exact: true });
  await r.check("role link, name 'Skip to main content'", () => expect(skip).toHaveCount(1));
  await r.check("href targets the main landmark id", async () => {
    await expect(skip).toHaveAttribute("href", "#main-content");
    await expect(page.getByRole("main")).toHaveAttribute("id", "main-content");
  });
  await r.check("activating it lands in the main landmark", async () => {
    await skip.focus();
    await page.keyboard.press("Enter");
    await expect(page.getByRole("main")).toBeFocused();
  });
  r.finish();
});

test("primary navigation: navigation landmark 'Primary', named groups, current page", async ({
  page,
}) => {
  const r = new Recorder(SCOPE, "primary-navigation");
  await page.goto(`/dashboards/cost?domain_id=${DOMAIN}`);
  const nav = page.getByRole("navigation", { name: "Primary" });
  await r.must("navigation landmark named 'Primary'", () => expect(nav).toHaveCount(1));
  await r.check("six named groups", async () => {
    for (const group of [
      "Overview",
      "Cost & usage",
      "Agents",
      "Quality",
      "Governance",
      "Reports",
    ]) {
      await expect(nav.getByRole("group", { name: group })).toHaveCount(1);
    }
  });
  await r.check("current page link carries aria-current=page", () =>
    expect(nav.getByRole("link", { name: "Cost dashboard", exact: true })).toHaveAttribute(
      "aria-current",
      "page",
    ),
  );
  await r.check("aria snapshot: the cost group lists its links", () =>
    expect(nav.getByRole("group", { name: "Cost & usage" })).toMatchAriaSnapshot(`
      - group "Cost & usage":
        - link "Cost dashboard"
        - link "Latency dashboard"
        - link "Coverage dashboard"
        - link "Reconciliation"
    `),
  );
  r.finish();
});

test("user menu: menu button, menu items and the selected state (theme mode)", async ({ page }) => {
  const r = new Recorder(SCOPE, "user-menu-theme-picker");
  await seedPreferences(page, { mode: "dark" });
  await page.goto(`/?domain_id=${DOMAIN}`);
  const trigger = page.getByRole("button", { name: "Account: Viewer" });
  await r.check("trigger is a button that announces a menu (aria-haspopup)", () =>
    expect(trigger).toHaveAttribute("aria-haspopup", "menu"),
  );
  await trigger.click();
  await r.must("menu opens", () => expect(page.getByRole("menu")).toBeVisible());
  await r.check("trigger exposes aria-expanded=true while open", () =>
    expect(trigger).toHaveAttribute("aria-expanded", "true"),
  );
  await r.check("aria snapshot: mode radios with the selected state", () =>
    expect(page.getByRole("menu")).toMatchAriaSnapshot(`
      - 'menu "Account: Viewer"':
        - group "Theme mode":
          - menuitemradio "Light"
          - menuitemradio "Dark" [checked]
          - menuitemradio "High contrast"
    `),
  );
  await r.check("a selection change is conveyed (aria-checked moves)", async () => {
    await page.getByRole("menuitemradio", { name: "High contrast" }).click();
    await trigger.click();
    await expect(page.getByRole("menuitemradio", { name: "High contrast" })).toBeChecked();
    await expect(page.getByRole("menuitemradio", { name: "Dark" })).not.toBeChecked();
  });
  r.finish();
});

test("user menu: pack names and the selected pack; no meaningless logo text", async ({ page }) => {
  const r = new Recorder(SCOPE, "user-menu-theme-pack-picker");
  await seedPreferences(page, { mode: "light", packId: "sample-agency" });
  await page.goto(`/?domain_id=${DOMAIN}`);
  await page.getByRole("button", { name: "Account: Viewer" }).click();
  await r.must("menu opens", () => expect(page.getByRole("menu")).toBeVisible());
  await r.check("aria snapshot: pack radios with the selected pack", () =>
    expect(page.getByRole("menu")).toMatchAriaSnapshot(`
      - 'menu "Account: Viewer"':
        - group "Theme pack":
          - menuitemradio "Neutral"
          - menuitemradio "Sample Agency" [checked]
    `),
  );
  await r.check("no header image is announced without a text alternative", async () => {
    const bad = await page
      .locator("header img")
      .evaluateAll((imgs) =>
        imgs.filter((i) => !i.hasAttribute("alt")).map((i) => i.outerHTML.slice(0, 80)),
      );
    expect(bad).toEqual([]);
  });
  await r.check("no decorative logo placeholder carries a name", async () => {
    const named = await page
      .locator("header [role='img']")
      .evaluateAll((els) => els.filter((e) => (e.getAttribute("aria-label") ?? "") !== "").length);
    expect(named).toBe(0);
  });
  r.finish();
});

test("sandbox toggle: announced as a switch with its on or off state", async ({ page }) => {
  const r = new Recorder(SCOPE, "sandbox-toggle");
  await seedPreferences(page, { mode: "light" });
  await page.goto(`/?domain_id=${DOMAIN}`);
  const toggle = page.getByRole("switch", { name: "Sandbox mode" });
  await r.check("role switch named 'Sandbox mode', off", async () => {
    await expect(toggle).toHaveCount(1);
    await expect(toggle).not.toBeChecked();
  });
  await toggle.focus();
  await page.keyboard.press("Space");
  await r.check("aria snapshot: switch is checked when on", () =>
    expect(toggle).toMatchAriaSnapshot(`- switch "Sandbox mode" [checked]`),
  );
  r.note(
    "checklist wording",
    "Checklist expects the switch to be announced with 'On: synthetic data only' or 'Off'. The product names the switch 'Sandbox mode' and exposes on/off only through the checked state (strings toggleOn and toggleOff in features/sandbox/strings.ts are defined but not rendered). A screen reader will say 'Sandbox mode, switch, on/off'. Human tester to confirm that wording is acceptable.",
  );
  r.finish();
});

test("sandbox banner: region 'Sandbox mode: synthetic data only' found by landmark navigation", async ({
  page,
}) => {
  const r = new Recorder(SCOPE, "sandbox-banner");
  await seedPreferences(page, { mode: "light", sandbox: true });
  await page.goto(`/?domain_id=${DOMAIN}`);
  const banner = page.getByRole("region", { name: "Sandbox mode: synthetic data only" });
  await r.check("region with the exact name", () => expect(banner).toHaveCount(1));
  await r.check("aria snapshot: region with its text", () =>
    expect(banner).toMatchAriaSnapshot(`
      - 'region "Sandbox mode: synthetic data only"':
        - text: Sandbox mode is on. You are working with a synthetic dataset. No real data is read or changed.
    `),
  );
  await r.check(
    "the banner is a landmark outside main (reachable by landmark navigation)",
    async () => {
      expect(await banner.evaluate((el) => el.closest("main") === null)).toBe(true);
    },
  );
  r.finish();
});

test("map table (treegrid): name, level, expanded state, polite detail live region", async ({
  page,
}) => {
  const r = new Recorder(SCOPE, "map-table-treegrid");
  await seedPreferences(page, { mode: "light" });
  await page.goto(`/map/table?domain_id=${DOMAIN}`);
  const grid = page.getByRole("treegrid", { name: "Map nodes" });
  await r.must("treegrid named 'Map nodes'", () => expect(grid).toBeVisible());
  const cluster = grid.locator("tr[data-row-key]").first();
  await r.check("cluster row has aria-level 1 and aria-expanded=false", async () => {
    await expect(cluster).toHaveAttribute("aria-level", "1");
    await expect(cluster).toHaveAttribute("aria-expanded", "false");
  });
  await r.check("rows are announced with a name (row label text)", async () => {
    const unnamed = await grid
      .locator("tr[data-row-key]")
      .evaluateAll((rows) => rows.filter((row) => (row.textContent ?? "").trim() === "").length);
    expect(unnamed).toBe(0);
  });
  await cluster.focus();
  await page.keyboard.press("Enter");
  await r.check(
    "after Enter the cluster is aria-expanded=true and children are level 2",
    async () => {
      await expect(cluster).toHaveAttribute("aria-expanded", "true");
      await expect(grid.locator("tr[data-row-key][aria-level='2']").first()).toBeVisible();
    },
  );
  await r.check("the detail region is a polite live region", async () => {
    const detail = page.getByTestId("detail");
    await expect(detail).toHaveAttribute("aria-live", "polite");
    await grid.locator("tr[data-row-key][aria-level='2']").first().focus();
    await page.keyboard.press("Enter");
    await expect(detail).not.toBeEmpty();
  });
  await r.check("coverage text is exposed as text, not colour alone", () =>
    expect(page.getByTestId("coverage")).toContainText("Coverage:"),
  );
  r.finish();
});

test("map page (WebGL): named region, coverage and live-status text, table link", async ({
  page,
}) => {
  const r = new Recorder(SCOPE, "map-page-webgl");
  await seedPreferences(page, { mode: "light" });
  await page.goto(`/map?domain_id=${DOMAIN}`);
  await expect(
    page.locator("[data-testid='map-canvas'][data-node-count]:not([data-node-count='0'])"),
  ).toBeVisible({ timeout: 30_000 });
  await r.check("region whose name starts with 'Agent topology map'", () =>
    expect(page.getByRole("region", { name: /^Agent topology map/ })).toHaveCount(1),
  );
  await r.check("the region name points to the table equivalent", () =>
    expect(
      page.getByRole("region", {
        name: "Agent topology map (WebGL graphic). The table view is the accessible equivalent.",
      }),
    ).toHaveCount(1),
  );
  await r.check("live status is a status role with text", async () => {
    const status = page.getByTestId("live-status");
    await expect(status).toHaveAttribute("role", "status");
    await expect(status).not.toBeEmpty();
  });
  await r.check("animation status and node counts are text", async () => {
    await expect(page.getByTestId("animation-status")).not.toBeEmpty();
    await expect(page.getByTestId("node-count")).not.toBeEmpty();
  });
  await r.check("the 'View as table' link is found by role", () =>
    expect(page.getByRole("link", { name: "View as table" })).toHaveCount(1),
  );
  await r.check("reduce-motion is a labelled switch", () =>
    expect(page.getByRole("switch", { name: /reduce motion/i })).toHaveCount(1),
  );
  r.note(
    "checklist wording",
    "Checklist says region named 'Agent topology map'. The product name is 'Agent topology map (WebGL graphic). The table view is the accessible equivalent.' (a longer name that starts with the expected text). Coverage and truncation text are rendered on the map page as status text; the table view carries the coverage text asserted in the treegrid row.",
  );
  r.finish();
});

test("chart (sandboxed iframe): meaningful title, table with accessible name and headers, sources text", async ({
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
  await r.check("iframe has a non-empty title", async () => {
    const title = (await page.locator("iframe").getAttribute("title")) ?? "";
    expect(title.trim().length).toBeGreaterThan(0);
  });
  await r.check("tablist 'Chart view' with Chart and Table tabs", () =>
    expect(page.getByRole("tablist", { name: "Chart view" })).toMatchAriaSnapshot(`
      - tablist "Chart view":
        - tab "Chart" [selected]
        - tab "Table"
    `),
  );
  await page.getByRole("tab", { name: "Table" }).click();
  const table = page.getByRole("table", { name: "Cost by month" });
  await r.check("table has an accessible name and column headers", async () => {
    await expect(table).toBeVisible();
    await expect(table.getByRole("columnheader")).not.toHaveCount(0);
    const unnamed = await table
      .getByRole("columnheader")
      .evaluateAll((hs) => hs.filter((h) => (h.textContent ?? "").trim() === "").length);
    expect(unnamed).toBe(0);
  });
  await r.check("sources text is present as text", () =>
    expect(page.getByText(/^Sources:/)).toBeVisible(),
  );
  r.note(
    "checklist wording",
    "Checklist says the table is announced 'with caption and headers'. The product gives the table an accessible name through aria-label (the chart title) rather than a <caption> element; the announced name is equivalent.",
  );
  r.finish();
});

test("reports: table headers, status text, and dialogs announcing their title", async ({
  page,
}) => {
  const r = new Recorder(SCOPE, "reports");
  await seedPreferences(page, { mode: "light" });
  await page.goto(`/reports?domain_id=${DOMAIN}`);
  const list = page.getByRole("table", { name: "Saved reports" });
  await r.must("table named 'Saved reports'", () => expect(list).toBeVisible());
  await r.check(
    "column headers Title, Publication, Updated (owner is part of the title cell)",
    () => expect(list.getByRole("columnheader")).toHaveText(["Title", "Publication", "Updated"]),
  );
  await r.check("publication state is text in each row", async () => {
    const empty = await list
      .locator("tbody tr")
      .evaluateAll((rows) => rows.filter((row) => (row.textContent ?? "").trim() === "").length);
    expect(empty).toBe(0);
    await expect(
      list.getByText(/Not published|Awaiting approval|Published|Rejected/).first(),
    ).toBeVisible();
  });
  await page.goto(`/reports/view?domain_id=${DOMAIN}&report_id=rpt-seed-own`);
  await expect(page.getByTestId("run-section")).toBeVisible();
  await r.check("publication badge is text", () =>
    expect(page.getByTestId("publication-badge")).not.toBeEmpty(),
  );
  await page.getByRole("button", { name: "Share", exact: true }).click();
  await r.check("the Share dialog is a dialog named 'Share report'", () =>
    expect(page.getByRole("dialog", { name: "Share report" })).toBeVisible(),
  );
  r.finish();
});

test("copilot: log, turns, citations, refusals and tool notices in order", async ({ page }) => {
  const r = new Recorder(SCOPE, "copilot-panel");
  await seedPreferences(page, { mode: "light" });
  await page.goto(`/?domain_id=${DOMAIN}`);
  const toggle = page.getByRole("button", { name: "Open assistant" });
  await r.check("the toggle exposes aria-expanded=false", () =>
    expect(toggle).toHaveAttribute("aria-expanded", "false"),
  );
  await toggle.click();
  await r.check("region 'Assistant' with a heading", async () => {
    await expect(page.getByRole("region", { name: "Assistant" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Assistant", level: 2 })).toBeVisible();
  });
  await r.check("log 'Conversation' is polite with additions and text relevance", async () => {
    const log = page.getByRole("log", { name: "Conversation" });
    await expect(log).toHaveAttribute("aria-live", "polite");
    await expect(log).toHaveAttribute("aria-relevant", "additions text");
  });
  const input = page.getByRole("textbox", { name: "Ask the assistant" });
  await input.fill("fixture:answered how much did we spend?");
  await page.getByRole("button", { name: "Send" }).click();
  await r.check("an answered turn: citations are a named list in the log", async () => {
    await expect(page.getByTestId("assistant-turn")).toHaveAttribute("data-status", "answered");
    const cites = page.getByRole("list", { name: "Sources" });
    await expect(cites.getByRole("listitem")).toHaveCount(3);
    expect(await cites.evaluate((el) => el.closest("[role='log']") !== null)).toBe(true);
  });
  await r.check("freshness is text (Fresh, Stale, Freshness unknown)", async () => {
    const cites = page.getByTestId("citations");
    await expect(cites).toContainText("Fresh");
    await expect(cites).toContainText("Stale");
    await expect(cites).toContainText("Freshness unknown");
  });
  await r.check("the chart is a titled iframe inside the log", () =>
    expect(page.locator("iframe[title='Chart from the assistant']")).toHaveCount(1),
  );
  await input.fill("fixture:abstain what is the meaning of life?");
  await page.keyboard.press("Enter");
  await r.check("a refusal-style abstention is text with its reason code", () =>
    expect(page.getByTestId("abstain")).toContainText("no_authorized_evidence"),
  );
  await input.fill("fixture:denied export everything");
  await page.keyboard.press("Enter");
  await r.check("a denial and the refused tool are text", async () => {
    await expect(page.getByTestId("denied")).toContainText("refused");
    await expect(page.getByTestId("tools").last()).toContainText("export_data: refused");
  });
  await input.fill("fixture:error");
  await page.keyboard.press("Enter");
  await r.check("an error turn is role=alert", () =>
    expect(
      page.getByRole("alert").filter({ hasText: "The model endpoint is unavailable." }),
    ).toBeVisible(),
  );
  r.finish();
});

test("actions: dialog title, target and version, state badges as text", async ({
  page,
  request,
}) => {
  const r = new Recorder(SCOPE, "actions-confirm-dialog");
  expect((await request.post(`${MOCK_API_URL}/__e2e/reset/${INTENT_EXPIRED}`)).status()).toBe(204);
  await seedPreferences(page, { mode: "light" });
  await page.goto(`/actions/detail?domain_id=${DOMAIN}&intent_id=${INTENT_EXPIRED}`);
  await r.check("state badge is read as text", async () => {
    const badge = page.getByTestId("state-badge").first();
    await expect(badge).toBeVisible();
    await expect(badge).not.toBeEmpty();
  });
  await page.getByRole("button", { name: "Review and confirm" }).click();
  const dialog = page.getByRole("alertdialog", { name: "Confirm this change" });
  await r.must("the dialog is announced with its title 'Confirm this change'", () =>
    expect(dialog).toBeVisible(),
  );
  await r.check("the dialog is described by its content (aria-describedby)", () =>
    expect(dialog).toHaveAttribute("aria-describedby", "confirm-body"),
  );
  await r.check("target, version and exact change are a labelled description list", async () => {
    await expect(dialog.getByText("Target", { exact: true })).toBeVisible();
    await expect(dialog.getByText("Target version", { exact: true })).toBeVisible();
    await expect(dialog.getByText("Exact change", { exact: true })).toBeVisible();
    await expect(dialog.getByTestId("confirm-target")).not.toBeEmpty();
    await expect(dialog.getByTestId("confirm-version")).not.toBeEmpty();
  });
  await r.check("the countdown is a timer and the validity text is a polite status", async () => {
    await expect(dialog.getByRole("timer")).toBeVisible();
    await expect(dialog.getByTestId("confirm-status")).toHaveAttribute("aria-live", "polite");
  });
  r.note(
    "checklist wording",
    "Checklist says the dialog is opened by 'Review and confirm' (the trigger button name). The dialog's own title in the product is 'Confirm this change' and its role is alertdialog (modalType alert).",
  );
  r.finish();
});

// ---- per-route screen reader pre-check ---------------------------------------------------------

// A role with no quoted name in the aria snapshot is announced without a name.
const UNNAMED_CONTROL =
  /^\s*- (button|link|textbox|combobox|checkbox|radio|switch|tab|menuitem|menuitemradio|menuitemcheckbox|option|searchbox|slider|spinbutton|treeitem)(\s*\[[^\]]+\])*:?\s*$/;

for (const sample of ROUTE_SAMPLES) {
  test(`screen reader tree: ${sample.pattern} (${sample.name})`, async ({ page }) => {
    const r = new Recorder("sr-route", sample.pattern);
    await seedPreferences(page, { mode: "light" });
    await openSample(page, sample);
    await r.check("page has a non-empty title", async () => {
      expect((await page.title()).trim().length).toBeGreaterThan(0);
    });
    await r.check("exactly one main landmark and a visible h1 inside it", async () => {
      await expect(page.getByRole("main")).toHaveCount(1);
      await expect(page.getByRole("main").getByRole("heading", { level: 1 }).first()).toBeVisible();
    });
    await r.check("banner and 'Primary' navigation landmarks are present", async () => {
      await expect(page.getByRole("banner")).toHaveCount(1);
      await expect(page.getByRole("navigation", { name: "Primary" })).toHaveCount(1);
    });
    await r.check("every control in the accessibility tree has a name", async () => {
      const snapshot = await page.locator("body").ariaSnapshot();
      const unnamed = snapshot.split("\n").filter((line) => UNNAMED_CONTROL.test(line));
      expect(unnamed, `unnamed controls: ${unnamed.join(" | ")}`).toEqual([]);
    });
    r.finish();
  });
}
