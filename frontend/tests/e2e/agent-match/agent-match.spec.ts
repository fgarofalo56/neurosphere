import type { Page } from "@playwright/test";
import { expect, test } from "../../e2e-support/fixtures.ts";
import {
  MATCH_COLD_START_ENTITY,
  MATCH_EMPTY_TASK_TEXT,
  MATCH_GRAPH_ENTITY,
  MATCH_PARTIAL_TASK_TEXT,
  MATCH_REASON_VIEWER,
  MATCH_TASK_TEXT,
  MATCH_TELEMETRY_ENTITY,
} from "../../mock-api/features/agent-match.ts";
import { DOMAIN_OK } from "../../mock-api/server.ts";
import {
  analyze,
  blocking,
  describeBlocking,
  MODES,
  seedPreferences,
} from "../a11y/axe-support.ts";

// PRP-75 item 5: Find an agent against the mock API. The stub session carries the Viewer role,
// which the mock answers 403 on the match routes, so every test but the forbidden one acts as a
// distinct non-viewer persona (the mock reads the role from the fake token suffix and keys its
// match and feedback memory by role+domain). Distinct personas keep the parallel workers from
// seeing each other's feedback, and counts are still asserted relative to a read-back baseline.

const PAGE_URL = `/recommendations/find?domain_id=${encodeURIComponent(DOMAIN_OK)}`;

async function actAs(page: Page, persona: string): Promise<void> {
  const token = `ns-e2e-fake-token.${persona}`;
  await page.route("**/api/v1/**", (route) =>
    route.continue({ headers: { ...route.request().headers(), authorization: `Bearer ${token}` } }),
  );
}

async function ask(page: Page, task: string): Promise<void> {
  await page.getByTestId("match-task-input").fill(task);
  const answered = page.waitForResponse(
    (r) => /\/match$/.test(new URL(r.url()).pathname) && r.request().method() === "POST",
  );
  await page.getByTestId("match-submit").click();
  await answered;
}

async function metricValue(page: Page, label: string): Promise<number> {
  const card = page.getByTestId("match-metrics").getByText(label, { exact: true }).locator("..");
  const text = (await card.textContent()) ?? "";
  const m = /(\d+)\s*$/.exec(text.replace(label, "").trim());
  if (m === null) throw new Error(`no number for ${label} in "${text}"`);
  return Number(m[1]);
}

function card(page: Page, entityId: string) {
  return page.locator(`[data-testid='match-candidate'][data-entity-id='${entityId}']`);
}

test("ranks candidates best-first with score, confidence and an explanation", async ({ page }) => {
  await actAs(page, "Matchera");
  await page.goto(PAGE_URL);
  await expect(page.getByRole("heading", { level: 1, name: "Find an agent" })).toBeVisible();
  await expect(page.getByTestId("match-submit")).toHaveAttribute("aria-disabled", "true");
  await ask(page, MATCH_TASK_TEXT);

  const cards = page.getByTestId("match-candidate");
  await expect(cards).toHaveCount(3);
  const scores = (await page.getByTestId("match-score").allTextContents()).map(Number);
  expect(scores.every((s) => Number.isFinite(s))).toBe(true);
  expect([...scores].sort((a, b) => b - a)).toEqual(scores);
  await expect(cards.first()).toHaveAttribute("data-entity-id", MATCH_TELEMETRY_ENTITY);
  await expect(page.getByTestId("match-confidence").first()).not.toHaveText("");
  await expect(cards.first().getByTestId("match-explanation")).toBeVisible();
  await expect(cards.first().getByTestId("match-signal").first()).toHaveAttribute(
    "data-observed",
    /true|false/,
  );
  await expect(page.getByTestId("match-confidence-note")).toContainText("not a probability");
  await expect(page.getByTestId("match-status")).toContainText("3 results");
  await expect(card(page, MATCH_GRAPH_ENTITY).getByTestId("match-relations")).toBeVisible();
});

test("a cold-start candidate says no telemetry yet and never shows 0", async ({ page }) => {
  await actAs(page, "Matcherb");
  await page.goto(PAGE_URL);
  await ask(page, MATCH_TASK_TEXT);
  const cold = card(page, MATCH_COLD_START_ENTITY);
  await expect(cold.getByTestId("match-cold-start")).toBeVisible();
  const unobserved = cold.locator("[data-testid='match-signal'][data-observed='false']");
  expect(await unobserved.count()).toBeGreaterThan(0);
  for (const row of await unobserved.all()) {
    await expect(row).toContainText("No telemetry yet");
    await expect(row).toContainText("Not counted");
  }
  await expect(page.getByTestId("match-cold-start-banner")).toBeVisible();
  await expect(cold.getByTestId("match-confidence")).not.toHaveText("0");
});

test("catalog and map links point at the entity and the domain map", async ({ page }) => {
  await actAs(page, "Matcherc");
  await page.goto(PAGE_URL);
  await ask(page, MATCH_TASK_TEXT);
  const first = card(page, MATCH_TELEMETRY_ENTITY);
  const catalog = first.getByRole("link", { name: "Open in catalog" });
  const href = (await catalog.getAttribute("href")) ?? "";
  expect(href).toContain("/catalog/entity?");
  expect(new URL(href, "http://x").searchParams.get("entity_id")).toBe(MATCH_TELEMETRY_ENTITY);
  const map = first.getByRole("link", { name: "Show on map" });
  const mapHref = (await map.getAttribute("href")) ?? "";
  expect(new URL(mapHref, "http://x").pathname).toBe("/map");
  expect(new URL(mapHref, "http://x").searchParams.get("domain_id")).toBe(DOMAIN_OK);
});

test("accept shows after confirmation, survives a reload in the metrics, and can become reject", async ({
  page,
}) => {
  await actAs(page, "Matcherd");
  await page.goto(PAGE_URL);
  await expect(page.getByTestId("match-acceptance-rate")).toBeVisible();
  const accepts0 = await metricValue(page, "Accepts");
  await ask(page, MATCH_TASK_TEXT);
  const first = card(page, MATCH_TELEMETRY_ENTITY);
  await expect(first.getByTestId("match-decision")).toHaveText("No decision yet");

  const feedback = page.waitForResponse((r) => r.url().includes("/match/feedback"));
  await first.getByTestId("match-accept").click();
  expect((await feedback).status()).toBe(202);
  await expect(first.getByTestId("match-decision")).toHaveText("Accepted");
  await expect(first.getByTestId("match-accept")).toHaveAttribute("aria-pressed", "true");
  await expect.poll(() => metricValue(page, "Accepts")).toBe(accepts0 + 1);

  await page.reload();
  await expect(page.getByTestId("match-acceptance-rate")).toBeVisible();
  await expect.poll(() => metricValue(page, "Accepts")).toBe(accepts0 + 1);
  // The decision is not read back and the task text is not restored: the page starts clean.
  await expect(page.getByTestId("match-candidate")).toHaveCount(0);

  await ask(page, MATCH_TASK_TEXT);
  const again = card(page, MATCH_TELEMETRY_ENTITY);
  await again.getByTestId("match-accept").click();
  await expect(again.getByTestId("match-decision")).toHaveText("Accepted");
  await again.getByTestId("match-reject").click();
  await expect(again.getByTestId("match-decision")).toHaveText("Rejected");
  await expect(again.getByTestId("match-reject")).toHaveAttribute("aria-pressed", "true");
  await expect(page.getByTestId("match-feedback-error")).toHaveCount(0);
});

test("a truncated match shows the partial banner with its reason", async ({ page }) => {
  await actAs(page, "Matchere");
  await page.goto(PAGE_URL);
  await ask(page, MATCH_PARTIAL_TASK_TEXT);
  await expect(page.getByTestId("match-partial")).toContainText("Results are partial.");
  await expect(page.getByTestId("match-partial")).toContainText("Result limit reached");
  expect(await page.getByTestId("match-candidate").count()).toBeGreaterThan(0);
});

test("a match with no candidates shows the empty state, not a blank list", async ({ page }) => {
  await actAs(page, "Matcherf");
  await page.goto(PAGE_URL);
  await ask(page, MATCH_EMPTY_TASK_TEXT);
  await expect(page.getByTestId("match-empty")).toContainText("No agents or tools match");
  await expect(page.getByTestId("match-candidate")).toHaveCount(0);
});

test("the viewer persona gets the forbidden state with its reason code", async ({ page }) => {
  await page.goto(PAGE_URL);
  await page.getByTestId("match-task-input").fill(MATCH_TASK_TEXT);
  const answered = page.waitForResponse(
    (r) => /\/match$/.test(new URL(r.url()).pathname) && r.request().method() === "POST",
  );
  await page.getByTestId("match-submit").click();
  expect((await answered).status()).toBe(403);
  await expect(page.getByTestId("forbidden-state")).toBeVisible();
  await expect(page.getByTestId("match-error-reason")).toContainText(MATCH_REASON_VIEWER);
  await expect(page.getByTestId("match-candidate")).toHaveCount(0);
});

test("the completeness tile says not available when the API has no completeness", async ({
  page,
}) => {
  await actAs(page, "Matcherg");
  await page.goto(PAGE_URL);
  await expect(page.getByTestId("match-completeness")).toContainText("Not available");
  await expect(page.getByTestId("match-outcome-note")).toContainText("not a target");
});

test("works by keyboard alone and keeps focus inside the card after a decision", async ({
  page,
}) => {
  await actAs(page, "Matcherh");
  await page.goto(PAGE_URL);
  await page.getByTestId("match-task-input").focus();
  await page.keyboard.type(MATCH_TASK_TEXT);
  const answered = page.waitForResponse((r) => /\/match$/.test(new URL(r.url()).pathname));
  await page.keyboard.press("Tab");
  await expect(page.getByTestId("match-submit")).toBeFocused();
  await page.keyboard.press("Enter");
  await answered;
  const first = card(page, MATCH_TELEMETRY_ENTITY);
  await expect(first).toBeVisible();

  const accept = first.getByTestId("match-accept");
  for (let i = 0; i < 40; i += 1) {
    if (await accept.evaluate((el) => el === document.activeElement)) break;
    await page.keyboard.press("Tab");
  }
  await expect(accept).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(first.getByTestId("match-decision")).toHaveText("Accepted");
  const inside = await first.evaluate((el) => el.contains(document.activeElement));
  expect(inside).toBe(true);
});

test("the task text never reaches the address or browser storage", async ({ page }) => {
  await actAs(page, "Matcheri");
  await page.goto(PAGE_URL);
  await ask(page, MATCH_TASK_TEXT);
  await expect(page.getByTestId("match-candidate").first()).toBeVisible();
  const needle = "quarterly invoice";
  expect(decodeURIComponent(page.url())).not.toContain(needle);
  const stored = await page.evaluate(() =>
    JSON.stringify([
      ...Object.entries(window.localStorage),
      ...Object.entries(window.sessionStorage),
    ]),
  );
  expect(stored).not.toContain(needle);
});

test.describe("axe on the results state", () => {
  for (const mode of MODES) {
    test(`has no blocking violations with results in ${mode}`, async ({ page }) => {
      await seedPreferences(page, { mode });
      await actAs(page, `Matcherax${mode === "light" ? "a" : mode === "dark" ? "b" : "c"}`);
      await page.goto(PAGE_URL);
      await ask(page, MATCH_TASK_TEXT);
      await expect(page.getByTestId("match-candidate")).toHaveCount(3);
      await page.waitForLoadState("networkidle");
      const { violations } = await analyze(page);
      expect(blocking(violations), describeBlocking(violations)).toEqual([]);
    });
  }
});
