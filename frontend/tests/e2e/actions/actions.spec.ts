import type { APIRequestContext, Page } from "@playwright/test";
import { MOCK_API_URL, expect, test } from "../../e2e-support/fixtures.ts";
import { axeViolations } from "../../helpers/axe.ts";
import {
  DOMAIN_FORBIDDEN,
  DOMAIN_OK,
  DOMAIN_VIEWER,
  INTENT_ADVISORY,
  INTENT_EXPIRED,
  INTENT_REVIEW,
  INTENT_STALE,
  ITEM_INSIGHT,
  ITEM_MAKER_CHECKER,
  ITEM_SUPERSEDED,
  ITEM_VIEWER,
} from "../../mock-api/server.ts";

// PRP-17 item 7b: the governed-action button flow and the review queue through the stubbed
// sign-in against the mock API. The domain rides in the APP url (`domain_id`) and in the API PATH.
// Authorization is whatever the API answers: the Viewer case relies on the real 403, never on a
// hidden control. Specs reset the seeded records they mutate, so reruns and parallel workers
// stay independent.

const TARGET = "commercial:e2e:foundry:model_deployment:support-gpt";

async function reset(request: APIRequestContext, id: string): Promise<void> {
  const response = await request.post(`${MOCK_API_URL}/__e2e/reset/${id}`);
  expect(response.status()).toBe(204);
}

function detailUrl(intentId: string, domain = DOMAIN_OK): string {
  const p = new URLSearchParams({ domain_id: domain, intent_id: intentId });
  return `/actions/detail?${p.toString()}`;
}

function itemUrl(itemId: string, domain = DOMAIN_OK): string {
  const p = new URLSearchParams({ domain_id: domain, item_id: itemId });
  return `/review/item?${p.toString()}`;
}

async function openDialog(page: Page, intentId: string): Promise<void> {
  await page.goto(detailUrl(intentId));
  await page.getByRole("button", { name: "Review and confirm" }).click();
  await expect(page.getByTestId("confirmation-dialog")).toBeVisible();
}

test.describe("button flow", () => {
  test("drafts, validates, shows the exact change in the dialog and confirms", async ({ page }) => {
    await page.goto(`/actions/propose?domain_id=${encodeURIComponent(DOMAIN_OK)}`);
    await page.getByLabel("Target model deployment (canonical id)", { exact: true }).fill(TARGET);
    await page.getByLabel("Target version (ETag)", { exact: true }).fill("etag-9");
    await page.getByLabel("New model name", { exact: true }).fill("gpt-4.1-mini");
    await page.getByLabel("New model version (optional)", { exact: true }).fill("2026-04-14");

    const draft = page.waitForResponse(
      (r) => r.url().includes("/intents") && r.request().method() === "POST",
    );
    await page.getByRole("button", { name: "Draft model swap" }).click();
    expect((await draft).status()).toBe(201);
    await expect(page.getByTestId("state-badge")).toHaveText("drafted");

    await page.getByRole("button", { name: "Validate" }).click();
    await expect(page.getByTestId("state-badge")).toHaveText("validated");

    await page.getByRole("button", { name: "Request confirmation" }).click();
    const dialog = page.getByTestId("confirmation-dialog");
    await expect(dialog).toBeVisible();
    await expect(dialog.getByTestId("confirm-target")).toHaveText(TARGET);
    await expect(dialog.getByTestId("confirm-version")).toHaveText("etag-9");
    const ops = dialog.getByTestId("diff-op");
    await expect(ops).toHaveCount(2);
    await expect(ops.nth(0)).toContainText("/properties/model/name");
    await expect(ops.nth(0)).toContainText("gpt-4.1-mini");
    await expect(ops.nth(1)).toContainText("/properties/model/version");
    await expect(ops.nth(1)).toContainText("2026-04-14");
    await expect(dialog.getByTestId("confirm-expiry")).toHaveText(/^\d{4}-\d{2}-\d{2}T/);
    await expect(dialog.getByTestId("confirm-countdown")).toHaveText(/^\d+:\d{2}$/);

    const confirm = page.waitForResponse((r) => r.url().endsWith("/confirm"));
    await dialog.getByRole("button", { name: "Confirm and send for approval" }).click();
    expect((await confirm).status()).toBe(200);
    await expect(dialog).toHaveCount(0);
    await expect(page.getByTestId("awaiting-approval")).toContainText(
      "Waiting for a reviewer to approve this action.",
    );
    await expect(page.getByTestId("state-badge")).toHaveText("awaiting_approval");
  });

  test("an expired confirmation cannot be submitted", async ({ page, request }) => {
    await reset(request, INTENT_EXPIRED);
    await openDialog(page, INTENT_EXPIRED);
    const dialog = page.getByTestId("confirmation-dialog");
    await expect(dialog.getByTestId("confirm-status")).toContainText(
      "This confirmation has expired. Re-validate the change to get a new one.",
    );
    await expect(
      dialog.getByRole("button", { name: "Confirm and send for approval" }),
    ).toBeDisabled();
  });

  test("a stale target version is reported and nothing is assumed to have run", async ({
    page,
    request,
  }) => {
    await reset(request, INTENT_STALE);
    await openDialog(page, INTENT_STALE);
    const dialog = page.getByTestId("confirmation-dialog");
    const confirm = page.waitForResponse((r) => r.url().endsWith("/confirm"));
    await dialog.getByRole("button", { name: "Confirm and send for approval" }).click();
    const response = await confirm;
    expect(response.status()).toBe(409);
    expect(response.headers()["content-type"]).toContain("application/problem+json");
    expect(((await response.json()) as { reason: string }).reason).toBe("target_version_changed");
    await expect(dialog.getByTestId("action-error")).toContainText(
      "The target changed since you validated it.",
    );
    await expect(page.getByTestId("state-badge").first()).toHaveText("awaiting_confirmation");
  });

  test("an advisory intent says so and offers no execute control", async ({ page }) => {
    await page.goto(detailUrl(INTENT_ADVISORY));
    await expect(page.getByTestId("advisory-note")).toContainText("Advisory only");
    await expect(page.getByTestId("workflow")).toHaveCount(0);
    await expect(
      page.getByRole("button", { name: /validate|confirm|execute|run|approve/i }),
    ).toHaveCount(0);
  });

  test("an emergency switch shows a banner", async ({ page }) => {
    // The switch is global on the shared mock, so only this page sees it flipped.
    await page.route("**/api/v1/actions/emergency-disable", (route) =>
      route.fulfill({
        json: {
          disabled: true,
          reason: "Synthetic drill: connector under maintenance",
          changed_by: "p-operator",
          changed_at: "2026-10-20T10:00:00Z",
        },
        headers: { "access-control-allow-origin": "*" },
      }),
    );
    await page.goto(detailUrl(INTENT_ADVISORY));
    const banner = page.getByTestId("emergency-banner");
    await expect(banner).toContainText("Action execution is disabled");
    await expect(banner).toContainText("connector under maintenance");
  });

  test("a domain outside the caller's scope shows the forbidden state", async ({ page }) => {
    const api = page.waitForResponse((r) => r.url().includes("/api/v1/actions/domains/"));
    await page.goto(`/actions?domain_id=${encodeURIComponent(DOMAIN_FORBIDDEN)}`);
    expect((await api).status()).toBe(403);
    await expect(page.getByTestId("forbidden-state")).toContainText(
      "You do not have access to this domain",
    );
    await expect(page.getByTestId("action-row")).toHaveCount(0);
  });
});

test.describe("review", () => {
  test("a reviewer approves a maker-checker item", async ({ page, request }) => {
    await reset(request, ITEM_MAKER_CHECKER);
    await reset(request, INTENT_REVIEW);
    await page.goto(itemUrl(ITEM_MAKER_CHECKER));
    const change = page.getByTestId("intent-under-review");
    await expect(change.getByTestId("review-target")).toHaveText(TARGET);
    await expect(change.getByTestId("review-version")).toHaveText("etag-7");
    await expect(page.getByTestId("review-diff").locator("li")).toHaveCount(2);

    await page.getByLabel("Reason for your decision").fill("Diff matches the change request");
    const decision = page.waitForResponse((r) => r.url().endsWith("/decisions"));
    await page.getByRole("button", { name: "Approve" }).click();
    expect((await decision).status()).toBe(200);
    await expect(page.getByTestId("item-final")).toBeVisible();
    await expect(page.getByTestId("decision")).toHaveCount(1);
    await expect(page.getByTestId("decision-effective")).toHaveText("Effective");
    await expect(page.getByTestId("state-badge")).toHaveText("approved");
  });

  test("a superseded decision stays visible as history only", async ({ page }) => {
    await page.goto(itemUrl(ITEM_SUPERSEDED));
    await expect(page.getByTestId("decision")).toHaveCount(2);
    await expect(page.getByTestId("decision-effective")).toHaveCount(1);
    await expect(page.getByTestId("decision-superseded")).toHaveCount(1);
    await expect(page.getByText("Superseded decisions are history only")).toBeVisible();
    await expect(page.getByTestId("item-final")).toBeVisible();
  });

  test("an insight review item has no change under review", async ({ page }) => {
    await page.goto(itemUrl(ITEM_INSIGHT));
    await expect(page.getByTestId("review-item")).toBeVisible();
    await expect(page.getByTestId("intent-under-review")).toHaveCount(0);
    await expect(page.getByText("recommendation", { exact: true }).first()).toBeVisible();
  });

  test("the queue lists maker-checker and insight items", async ({ page }) => {
    await page.goto(`/review?domain_id=${encodeURIComponent(DOMAIN_OK)}`);
    await expect(page.getByTestId("review-row").first()).toBeVisible();
    const kinds = page.getByTestId("review-row").getByRole("link");
    await expect(kinds.filter({ hasText: "maker_checker" }).first()).toBeVisible();
    await expect(kinds.filter({ hasText: "recommendation" })).toHaveCount(1);
  });

  test("a Viewer deep link gets the permission message from the API 403", async ({ page }) => {
    await page.goto(itemUrl(ITEM_VIEWER, DOMAIN_VIEWER));
    await expect(page.getByTestId("intent-under-review")).toBeVisible();
    await page.getByLabel("Reason for your decision").fill("Looks fine");
    // The page does not hide the control: the API alone decides.
    const decision = page.waitForResponse((r) => r.url().endsWith("/decisions"));
    await page.getByRole("button", { name: "Approve" }).click();
    const response = await decision;
    expect(response.status()).toBe(403);
    expect(response.headers()["content-type"]).toContain("application/problem+json");
    await expect(page.getByTestId("mutation-error")).toContainText(
      "You don't have permission to approve this item",
    );
    await expect(page.getByTestId("item-final")).toHaveCount(0);
  });
});

test.describe("accessibility", () => {
  test("actions list has no axe violations", async ({ page }) => {
    await page.goto(`/actions?domain_id=${encodeURIComponent(DOMAIN_OK)}`);
    await expect(page.getByTestId("action-row").first()).toBeVisible();
    expect(await axeViolations(page)).toEqual([]);
  });

  test("action detail with the dialog open has no axe violations", async ({ page, request }) => {
    await reset(request, INTENT_STALE);
    await openDialog(page, INTENT_STALE);
    await expect(page.getByTestId("confirm-status")).toContainText("Confirmation is valid.");
    expect(await axeViolations(page)).toEqual([]);
  });

  test("review queue has no axe violations", async ({ page }) => {
    await page.goto(`/review?domain_id=${encodeURIComponent(DOMAIN_OK)}`);
    await expect(page.getByTestId("review-row").first()).toBeVisible();
    expect(await axeViolations(page)).toEqual([]);
  });

  test("review item has no axe violations", async ({ page }) => {
    await page.goto(itemUrl(ITEM_SUPERSEDED));
    await expect(page.getByTestId("decision")).toHaveCount(2);
    await expect(page.getByTestId("intent-under-review")).toBeVisible();
    expect(await axeViolations(page)).toEqual([]);
  });
});

test("navigation lists the actions and review entries", async ({ page }) => {
  await page.goto("/");
  const nav = page.getByRole("navigation", { name: "Primary" });
  await expect(nav.getByRole("link", { name: "Actions" })).toBeVisible();
  await expect(nav.getByRole("link", { name: "Review" })).toBeVisible();
});
