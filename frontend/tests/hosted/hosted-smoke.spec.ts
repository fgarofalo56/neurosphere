import AxeBuilder from "@axe-core/playwright";
import { existsSync, readFileSync } from "node:fs";
import { expect, test, type Page } from "@playwright/test";
import { SESSION_STORAGE_FILE } from "../../playwright.hosted.config";
import { WCAG_TAGS } from "../helpers/axe.ts";

/**
 * PRP-32 item 6, MANUAL gate (see playwright.hosted.config.ts): one signed-in pass over the
 * deployed demo. It needs the synthetic seed from item 5; against an unseeded environment the
 * tiles and domain switcher fail, which is the point.
 */

/** Same rules as `axeViolations`, minus Fluent's Tabster focus sentinels (see copilot.spec.ts). */
async function axeViolationsIgnoringTabster(page: Page) {
  const results = await new AxeBuilder({ page })
    .withTags([...WCAG_TAGS])
    .exclude("[data-tabster-dummy]")
    .analyze();
  return results.violations.map((v) => ({ id: v.id, impact: v.impact, nodes: v.nodes.length }));
}

/** Replays the saved MSAL `sessionStorage` (when a dump exists) into each new document. */
async function restoreSession(page: Page): Promise<void> {
  if (!existsSync(SESSION_STORAGE_FILE)) return;
  const entries = JSON.parse(readFileSync(SESSION_STORAGE_FILE, "utf8")) as Record<string, string>;
  await page.addInitScript((saved: Record<string, string>) => {
    for (const [key, value] of Object.entries(saved)) {
      if (window.sessionStorage.getItem(key) === null) window.sessionStorage.setItem(key, value);
    }
  }, entries);
}

test("hosted demo: shell, domains, overview, map and copilot, with axe on shell and overview", async ({
  page,
}) => {
  await restoreSession(page);
  const domainsAnswer = page.waitForResponse(
    (r) => r.url().includes("/api/v1/me/domains") && r.status() === 200,
  );
  await page.goto("/");
  const domains = (await (await domainsAnswer).json()) as { items: { domain_id: string }[] };

  // Shell renders, signed in, and the synthetic domains are offered.
  await expect(page.getByRole("main")).toBeVisible();
  await expect(page.locator("main h1").first()).toBeVisible();
  await expect(page.getByTestId("demo-banner")).toHaveCount(0);
  expect(domains.items.length).toBeGreaterThan(0);
  const switcher = page.getByRole("combobox", { name: "Domain" });
  await expect(switcher).toBeVisible();
  await switcher.click();
  await expect(page.getByRole("option").first()).toBeVisible();
  await page.keyboard.press("Escape");

  const domain = encodeURIComponent(domains.items[0]?.domain_id ?? "");

  // Overview tiles carry data.
  await page.goto(`/?domain_id=${domain}`);
  await expect(page.getByTestId("tile-cost").getByTestId("cost-row").first()).toBeVisible();
  await expect(page.getByTestId("tile-map").getByTestId("map-coverage")).toBeVisible();
  await page.waitForLoadState("networkidle");

  // Accessibility: the shell and the overview (the overview is the page we are on).
  expect(await axeViolationsIgnoringTabster(page)).toEqual([]);

  // The map renders at least one node.
  await page.goto(`/map?domain_id=${domain}`);
  const canvas = page.getByTestId("map-canvas");
  await expect(canvas).toBeVisible();
  await expect
    .poll(async () => Number((await canvas.getAttribute("data-node-count")) ?? "0"), {
      timeout: 60_000,
    })
    .toBeGreaterThan(0);

  // Copilot: a streamed answer, or the disabled/unavailable reason (acceptable when Foundry is
  // not wired; the reason must be shown, never a blank panel).
  await page.goto(`/?domain_id=${domain}`);
  await page.getByRole("button", { name: "Open assistant" }).click();
  await expect(page.getByRole("region", { name: "Assistant" })).toBeVisible();
  await page.getByRole("textbox", { name: "Ask the assistant" }).fill("Summarize this domain.");
  await page.getByRole("button", { name: "Send" }).click();
  await expect(
    page.getByTestId("answer-text").or(page.getByTestId("turn-error")).first(),
  ).toBeVisible({ timeout: 90_000 });
});
