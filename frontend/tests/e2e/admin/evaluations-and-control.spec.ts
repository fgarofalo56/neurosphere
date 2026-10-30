import AxeBuilder from "@axe-core/playwright";
import type { Page } from "@playwright/test";
import { expect, test } from "../../e2e-support/fixtures.ts";
import { WCAG_TAGS } from "../../helpers/axe.ts";
import { EVAL_DOMAIN, EVAL_SUBJECT_A, EVAL_TOTAL } from "../../mock-api/features/evaluations.ts";

// PRP-31 item 8: evaluation results and the execution kill switch. Results come from the mock
// API. The kill switch is a stateful in-test stub of /api/v1/actions/emergency-disable, because
// server.ts answers that path (GET-only, always enabled) before the feature registry runs, so the
// execution-control registry module cannot take it over. One stub serves both pages, so the
// /actions banner check still follows a real disable through the UI. Follow-up delta item: let
// the registry dispatch first for that path, then drop the stub and use the mock module.

const MODES = ["light", "dark", "high-contrast"] as const;
const EVAL_URL = `/evaluations?domain_id=${encodeURIComponent(EVAL_DOMAIN)}`;
const PATH_GLOB = "**/api/v1/actions/emergency-disable";
const ACTOR = "psn-e2e-admin";
const CORS = {
  "access-control-allow-origin": "*",
  "access-control-allow-methods": "GET, PUT, OPTIONS",
  "access-control-allow-headers": "*",
};

interface ControlView {
  disabled: boolean;
  reason: string | null;
  changed_by: string | null;
  changed_at: string | null;
}

/** Serves GET and PUT from one in-memory state; `allowWrite` false answers PUT with a 403. */
async function stubControl(page: Page, allowWrite: boolean): Promise<void> {
  let view: ControlView = { disabled: false, reason: null, changed_by: null, changed_at: null };
  await page.route(PATH_GLOB, async (route) => {
    const request = route.request();
    if (request.method() === "OPTIONS") {
      await route.fulfill({ status: 204, headers: CORS });
    } else if (request.method() === "PUT") {
      if (!allowWrite) {
        await route.fulfill({
          status: 403,
          contentType: "application/problem+json",
          headers: CORS,
          json: {
            schema_version: "1.0.0",
            type: "https://neurosphere.invalid/problems/forbidden",
            title: "Forbidden",
            status: 403,
            detail: "permission_missing",
            instance: "/api/v1/actions/emergency-disable",
            code: "forbidden",
            reason: "permission_missing",
            retryable: false,
            correlation_id: "corr-e2e-control",
          },
        });
        return;
      }
      const body = request.postDataJSON() as { disabled: boolean; reason: string | null };
      view = {
        disabled: body.disabled,
        reason: body.reason,
        changed_by: ACTOR,
        changed_at: "2026-10-30T12:00:00.000000Z",
      };
      await route.fulfill({ status: 200, headers: CORS, json: view });
    } else {
      await route.fulfill({ status: 200, headers: CORS, json: view });
    }
  });
}

async function axeViolations(page: Page) {
  const results = await new AxeBuilder({ page })
    .withTags([...WCAG_TAGS])
    .exclude("[data-tabster-dummy]")
    .analyze();
  return results.violations.map((v) => ({ id: v.id, impact: v.impact, nodes: v.nodes.length }));
}

test("evaluation results page by cursor and filter by subject and dimension", async ({ page }) => {
  await page.goto(EVAL_URL);
  await expect(page.getByTestId("evaluation-row")).toHaveCount(20);
  await expect(page.getByTestId("evaluations-count")).toContainText("20+");
  const row = page.getByTestId("evaluation-row").first();
  await expect(row).toContainText("0.8125 (scale 0 to 1)");
  await expect(row).toContainText("bootstrap, 0.7421875 to 0.8828125, level 0.95");

  await page.getByTestId("evaluations-more").click();
  await expect(page.getByTestId("evaluation-row")).toHaveCount(EVAL_TOTAL);
  await expect(page.getByTestId("evaluations-more")).toHaveCount(0);

  await page.getByLabel("Subject id").fill(EVAL_SUBJECT_A);
  await page.getByRole("combobox", { name: "Dimension" }).click();
  await page.getByRole("option", { name: "safety" }).click();
  await page.getByTestId("evaluations-apply").click();
  const rows = page.getByTestId("evaluation-row");
  await expect(rows.first()).toHaveAttribute("data-dimension", "safety");
  for (const r of await rows.all()) {
    await expect(r).toHaveAttribute("data-subject", EVAL_SUBJECT_A);
    await expect(r).toHaveAttribute("data-dimension", "safety");
  }
  await expect(page.getByTestId("evaluations-quality-link")).toHaveAttribute(
    "href",
    /\/quality\?domain_id=/,
  );
});

test("a domain outside the caller's scope shows the forbidden state", async ({ page }) => {
  const domain = encodeURIComponent("commercial:e2e:sandbox:domain:forbidden");
  await page.goto(`/evaluations?domain_id=${domain}`);
  await expect(page.getByTestId("forbidden-state")).toBeVisible();
  await expect(page.getByTestId("evaluation-row")).toHaveCount(0);
});

test("disable needs a reason code, then /actions shows the banner; enable clears it", async ({
  page,
}) => {
  await stubControl(page, true);
  await page.goto("/admin/execution-control");
  await expect(page.getByTestId("execution-pill")).toContainText("Execution is enabled");

  await page.getByTestId("execution-toggle").click();
  const dialog = page.getByTestId("change-confirm-dialog");
  await dialog.getByRole("textbox").fill("Not A Code");
  await dialog.getByRole("button", { name: "Confirm change" }).click();
  await expect(page.getByTestId("change-error")).toContainText("snake_case");
  await dialog.getByRole("textbox").fill("incident_review");
  await dialog.getByRole("button", { name: "Confirm change" }).click();

  await expect(page.getByTestId("execution-pill")).toContainText("Execution is disabled");
  await expect(page.getByTestId("execution-reason")).toHaveText("incident_review");
  await expect(page.getByTestId("execution-changed-by")).toHaveText(ACTOR);

  await page.goto("/actions");
  await expect(page.getByTestId("emergency-banner").first()).toContainText("incident_review");

  await page.goto("/admin/execution-control");
  await page.getByTestId("execution-toggle").click();
  const second = page.getByTestId("change-confirm-dialog");
  await second.getByRole("textbox").fill("drill_complete");
  await second.getByRole("button", { name: "Confirm change" }).click();
  await expect(page.getByTestId("execution-pill")).toContainText("Execution is enabled");
});

test("a caller without config.manage gets the API 403 on a change", async ({ page }) => {
  await stubControl(page, false);
  await page.goto("/admin/execution-control");
  await page.getByTestId("execution-toggle").click();
  const dialog = page.getByTestId("change-confirm-dialog");
  await dialog.getByRole("textbox").fill("incident_review");
  const put = page.waitForResponse(
    (r) => r.url().endsWith("/emergency-disable") && r.request().method() === "PUT",
  );
  await dialog.getByRole("button", { name: "Confirm change" }).click();
  expect((await put).status()).toBe(403);
  await expect(page.getByTestId("change-error")).toContainText("config.manage");
});

for (const mode of MODES) {
  test(`evaluations and execution control have no axe violations in ${mode}`, async ({ page }) => {
    await stubControl(page, true);
    await page.addInitScript((themeName) => {
      window.localStorage.setItem("ns.theme", JSON.stringify({ packId: "default", themeName }));
    }, mode);
    await page.goto(EVAL_URL);
    await expect(page.getByTestId("evaluation-row").first()).toBeVisible();
    await page.waitForLoadState("networkidle");
    expect(await axeViolations(page)).toEqual([]);

    await page.goto("/admin/execution-control");
    await expect(page.getByTestId("execution-pill")).toBeVisible();
    expect(await axeViolations(page)).toEqual([]);
    await page.getByTestId("execution-toggle").click();
    await expect(page.getByTestId("change-confirm-dialog")).toBeVisible();
    expect(await axeViolations(page)).toEqual([]);
  });
}
