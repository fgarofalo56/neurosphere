import type { APIRequestContext, Locator, Page } from "@playwright/test";
import { MOCK_API_URL, expect, test } from "../../e2e-support/fixtures.ts";
import { DOMAIN_OK, DOMAIN_VIEWER, INTENT_PLAN, PLAN_DIGEST } from "../../mock-api/server.ts";

// PRP-34 item 8: the APIM plan preview in the confirmation dialog, the audited observe/manage
// switch and the Grant and MCP server publication buttons, through the stubbed sign-in against
// the mock API. Every control only DRAFTS an action intent; the mock (like the real API) answers
// the refusals, so the specs assert what the server said, never a hidden control.

async function reset(request: APIRequestContext, id: string): Promise<void> {
  const response = await request.post(`${MOCK_API_URL}/__e2e/reset/${id}`);
  expect(response.status()).toBe(204);
}

function gatewaysUrl(domain = DOMAIN_OK): string {
  return `/gateways?${new URLSearchParams({ domain_id: domain }).toString()}`;
}

function publicationUrl(domain = DOMAIN_OK): string {
  return `/catalog/publication?${new URLSearchParams({ domain_id: domain }).toString()}`;
}

function panel(page: Page, name: string): Locator {
  return page.getByTestId("gateway-panel").filter({ has: page.getByRole("heading", { name }) });
}

test.describe("plan preview in the confirmation dialog", () => {
  test("shows the plan steps and the digest prefix beside the exact diff", async ({
    page,
    request,
  }) => {
    await reset(request, INTENT_PLAN);
    await page.goto(
      `/actions/detail?${new URLSearchParams({ domain_id: DOMAIN_OK, intent_id: INTENT_PLAN }).toString()}`,
    );
    await page.getByRole("button", { name: "Review and confirm" }).click();
    const dialog = page.getByTestId("confirmation-dialog");
    await expect(dialog).toBeVisible();

    await expect(dialog.getByTestId("plan-digest")).toContainText(PLAN_DIGEST.slice(0, 12));
    // The full digest is not dumped into the dialog: only the prefix.
    await expect(dialog.getByTestId("plan-digest")).not.toContainText(PLAN_DIGEST);
    const steps = dialog.getByTestId("plan-step");
    await expect(steps).toHaveCount(2);
    await expect(steps.nth(0).getByTestId("plan-step-type")).toHaveText("product");
    await expect(steps.nth(0).getByTestId("plan-step-name")).toHaveText("products/finance-analyst");
    await expect(steps.nth(1).getByTestId("plan-step-type")).toHaveText("product_api_link");
    // The API does not report create or found yet: the dialog says so instead of guessing.
    await expect(steps.nth(0).getByTestId("plan-step-expected")).toContainText("Not reported yet");
    // The exact diff (digest test operation plus the resources) is still listed in full.
    await expect(dialog.getByTestId("diff-op")).toHaveCount(3);
  });
});

test.describe("observe and manage switch", () => {
  test("shows mode, who and when, and the preflight with required and missing actions", async ({
    page,
  }) => {
    await page.goto(gatewaysUrl());
    const observe = panel(page, "apim-observe");
    await expect(observe.getByTestId("gateway-mode")).toHaveText("Observe");
    await expect(observe.getByTestId("preflight-status")).toHaveText("Failed");
    await expect(observe.getByTestId("preflight-required").locator("li")).toHaveCount(3);
    await expect(observe.getByTestId("preflight-missing")).toContainText(
      "Microsoft.ApiManagement/service/backends/write",
    );
    await expect(observe.getByTestId("observe-note")).toContainText("gateway_observe_mode");

    const manage = panel(page, "apim-manage");
    await expect(manage.getByTestId("gateway-mode")).toHaveText("Manage");
    await expect(manage.getByTestId("gateway-changed-by")).toHaveText("p-maker");
    await expect(manage.getByTestId("preflight-status")).toHaveText("Passed");
    await expect(manage.getByTestId("preflight-none-missing")).toBeVisible();
  });

  test("drafts the switch, links to the approval flow and never flips the mode itself", async ({
    page,
  }) => {
    await page.goto(gatewaysUrl());
    const observe = panel(page, "apim-observe");
    const draft = page.waitForResponse(
      (r) => r.url().endsWith("/mode") && r.request().method() === "POST",
    );
    await observe.getByRole("button", { name: "Draft switch to manage mode" }).click();
    expect((await draft).status()).toBe(201);
    const note = observe.getByTestId("mode-drafted");
    await expect(note).toContainText("Nothing has changed yet");
    await expect(observe.getByTestId("gateway-mode")).toHaveText("Observe");

    await note.getByRole("link", { name: "Open the approval flow" }).click();
    await expect(page.getByTestId("action-detail")).toBeVisible();
    await expect(page.locator("code", { hasText: "gateway_mode_change" }).first()).toBeVisible();
    await expect(page.getByTestId("state-badge")).toHaveText("drafted");
    await expect(page.getByRole("button", { name: "Validate" })).toBeVisible();
  });

  test("shows the server's refusal when an APIM action is running", async ({ page }) => {
    await page.goto(gatewaysUrl());
    const busy = panel(page, "apim-busy");
    await busy.getByRole("button", { name: "Draft switch to manage mode" }).click();
    const refusal = busy.getByTestId("mode-refusal");
    await expect(refusal).toContainText("An APIM action is running in this domain");
    await expect(refusal.getByTestId("mode-refusal-reason")).toHaveText("gateway_applying");
  });

  test("disables manage for a Government gateway and states why", async ({ page }) => {
    await page.goto(gatewaysUrl());
    const gov = panel(page, "apim-gov");
    await expect(gov.getByRole("button", { name: "Draft switch to manage mode" })).toBeDisabled();
    await expect(gov.getByTestId("government-blocked")).toContainText("Azure Government");
  });

  test("a caller without action.propose gets a disabled switch and a stated reason", async ({
    page,
  }) => {
    await page.goto(gatewaysUrl(DOMAIN_VIEWER));
    const viewer = panel(page, "apim-viewer");
    await expect(
      viewer.getByRole("button", { name: "Draft switch to manage mode" }),
    ).toBeDisabled();
    await expect(viewer.getByTestId("no-permission")).toBeVisible();
  });
});

test.describe("grant and MCP server publication", () => {
  test("a grant drafts an unpublish and links to the approval flow", async ({ page }) => {
    await page.goto(publicationUrl());
    const row = page.getByTestId("grant-row");
    await expect(row).toHaveCount(1);
    const draft = page.waitForResponse(
      (r) => r.url().endsWith("/unpublish") && r.request().method() === "POST",
    );
    await row.getByRole("button", { name: "Unpublish" }).click();
    expect((await draft).status()).toBe(201);
    const bar = row.getByTestId("publish-drafted");
    await expect(bar).toContainText("Nothing has changed yet");
    await bar.getByRole("link", { name: "Open the approval flow" }).click();
    await expect(page.getByTestId("action-detail")).toBeVisible();
    await expect(page.locator("code", { hasText: "grant_unpublish" }).first()).toBeVisible();
  });

  test("a grant publish collects the gateway and API, and an observe gateway is refused", async ({
    page,
  }) => {
    await page.goto(publicationUrl());
    const row = page.getByTestId("grant-row");
    await row.getByRole("button", { name: "Publish", exact: true }).click();
    const dialog = page.getByTestId("publish-dialog");
    await expect(dialog).toBeVisible();
    await dialog
      .getByRole("combobox", { name: "Gateway" })
      .selectOption({ label: "apim-observe (observe)" });
    await dialog.getByLabel("API id", { exact: false }).fill("finance-api");
    await dialog.getByRole("button", { name: "Draft publish" }).click();
    const refusal = dialog.getByTestId("publish-refusal");
    await expect(refusal).toContainText("observe mode");
    await expect(refusal.getByTestId("publish-refusal-reason")).toHaveText("gateway_observe_mode");

    await dialog
      .getByRole("combobox", { name: "Gateway" })
      .selectOption({ label: "apim-manage (manage)" });
    await dialog.getByRole("button", { name: "Draft publish" }).click();
    await expect(dialog).toHaveCount(0);
    await expect(row.getByTestId("publish-drafted")).toBeVisible();
  });

  test("an MCP server unpublish is two steps and the button names the next one", async ({
    page,
  }) => {
    await page.goto(publicationUrl());
    const published = page.getByTestId("mcp-row").filter({ hasText: "Finance tools" });
    await expect(published.getByTestId("mcp-next-unpublish")).toHaveText(
      "Next step: deny access (step 1 of 2).",
    );
    await expect(published.getByTestId("mcp-two-step")).toContainText("two steps");
    const draft = page.waitForResponse(
      (r) => r.url().endsWith("/unpublish") && r.request().method() === "POST",
    );
    await published.getByRole("button", { name: "Unpublish: deny (step 1 of 2)" }).click();
    expect((await draft).status()).toBe(201);
    await expect(published.getByTestId("drafted-stage")).toHaveText("deny");

    const denied = page.getByTestId("mcp-row").filter({ hasText: "Legacy tools" });
    await expect(denied.getByTestId("mcp-next-unpublish")).toHaveText(
      "Next step: remove the published server (step 2 of 2).",
    );
    await expect(
      denied.getByRole("button", { name: "Unpublish: remove (step 2 of 2)" }),
    ).toBeEnabled();

    const fresh = page.getByTestId("mcp-row").filter({ hasText: "New tools" });
    await expect(fresh.getByRole("button", { name: "Unpublish" })).toBeDisabled();
  });
});
