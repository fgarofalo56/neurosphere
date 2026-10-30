import AxeBuilder from "@axe-core/playwright";
import type { Page } from "@playwright/test";
import { expect, test } from "../../e2e-support/fixtures.ts";
import { WCAG_TAGS } from "../../helpers/axe.ts";
import {
  AUDIT_DOMAIN_EMPTY,
  AUDIT_DOMAIN_FINANCE,
  AUDIT_DOMAIN_HR,
  AUDIT_DOMAIN_UNCONFIGURED,
  AUDIT_FINANCE_COUNT,
  AUDIT_HR_BREAK_SEQUENCE,
} from "../../mock-api/features/audit.ts";

// PRP-31 item 5: the read-only audit log against the mock API. The stub session carries the
// Viewer role, so the auditor persona is applied to the audit calls only (the mock reads the role
// from the fake token suffix and stands in for the API's audit.read check). An auditor holds no
// data.read, so /me/domains is answered 403 here and the page must not need it.

const AUDITOR_TOKEN = "ns-e2e-fake-token.Auditor";
const MODES = ["light", "dark", "high-contrast"] as const;

async function actAsAuditor(page: Page): Promise<void> {
  await page.route("**/api/v1/audit/**", (route) =>
    route.continue({
      headers: { ...route.request().headers(), authorization: `Bearer ${AUDITOR_TOKEN}` },
    }),
  );
  await page.route("**/api/v1/me/domains", (route) =>
    route.fulfill({
      status: 403,
      contentType: "application/problem+json",
      json: {
        schema_version: "1.0.0",
        type: "https://neurosphere.invalid/problems/forbidden",
        title: "Forbidden",
        status: 403,
        detail: "no data.read",
        instance: "/api/v1/me/domains",
        code: "forbidden",
        retryable: false,
        correlation_id: "corr-e2e-me",
      },
    }),
  );
}

const url = (domain: string): string => `/audit?audit_domain=${encodeURIComponent(domain)}`;

async function axeViolations(page: Page) {
  const results = await new AxeBuilder({ page })
    .withTags([...WCAG_TAGS])
    .exclude("[data-tabster-dummy]")
    .analyze();
  return results.violations.map((v) => ({ id: v.id, impact: v.impact, nodes: v.nodes.length }));
}

test("an auditor-only token lists audit domains and reads records without /me/domains", async ({
  page,
}) => {
  await actAsAuditor(page);
  const domains = page.waitForResponse((r) => r.url().endsWith("/api/v1/audit/domains"));
  await page.goto("/audit");
  expect((await domains).status()).toBe(200);
  await expect(page.getByTestId("audit-row").first()).toBeVisible();
  await expect(page.getByRole("combobox", { name: "Audit domain" })).toContainText("Finance");
  await expect(page.getByTestId("forbidden-state")).toHaveCount(0);
  await expect(page.getByRole("button", { name: /export|copy|download/i })).toHaveCount(0);
});

test("records page by cursor and the drawer shows every field", async ({ page }) => {
  await actAsAuditor(page);
  await page.goto(url(AUDIT_DOMAIN_FINANCE));
  await expect(page.getByTestId("audit-row")).toHaveCount(25);
  const next = page.waitForResponse(
    (r) => r.url().includes("/records") && r.url().includes("cursor=25"),
  );
  await page.getByTestId("audit-more").click();
  expect((await next).status()).toBe(200);
  await expect(page.getByTestId("audit-row")).toHaveCount(AUDIT_FINANCE_COUNT);
  await expect(page.getByTestId("audit-more")).toHaveCount(0);
  await expect(page.getByTestId("audit-end")).toBeVisible();

  await page
    .locator('[data-testid="audit-row"][data-sequence="3"]')
    .getByTestId("audit-open")
    .click();
  const drawer = page.getByTestId("audit-drawer");
  await expect(drawer).toBeVisible();
  await expect(drawer).toContainText("Record hash");
  await expect(drawer).toContainText("corr-audit-3");
  await page.getByTestId("audit-drawer-close").click();
  await expect(drawer).toHaveCount(0);
});

test("verify shows valid, and a break position for a broken chain", async ({ page }) => {
  await actAsAuditor(page);
  await page.goto(url(AUDIT_DOMAIN_FINANCE));
  await page.getByTestId("audit-verify").click();
  await expect(page.getByTestId("audit-verify-result")).toContainText(
    `Chain is valid. ${AUDIT_FINANCE_COUNT} records checked.`,
  );

  await page.goto(url(AUDIT_DOMAIN_HR));
  await expect(page.getByTestId("audit-row").first()).toBeVisible();
  await page.getByTestId("audit-verify").click();
  await expect(page.getByTestId("audit-verify-result")).toContainText(
    `First break at sequence ${AUDIT_HR_BREAK_SEQUENCE}`,
  );
});

test("empty chain and unconfigured store are distinct states", async ({ page }) => {
  await actAsAuditor(page);
  await page.goto(url(AUDIT_DOMAIN_EMPTY));
  await expect(page.getByTestId("audit-empty")).toBeVisible();
  await page.goto(url(AUDIT_DOMAIN_UNCONFIGURED));
  await expect(page.getByTestId("audit-unconfigured")).toBeVisible();
  await expect(page.getByTestId("audit-empty")).toHaveCount(0);
});

test("a viewer token gets 403 and ForbiddenState", async ({ page }) => {
  const response = page.waitForResponse((r) => r.url().endsWith("/api/v1/audit/domains"));
  await page.goto("/audit");
  expect((await response).status()).toBe(403);
  await expect(page.getByTestId("forbidden-state")).toBeVisible();
  await expect(page.getByTestId("audit-row")).toHaveCount(0);
});

for (const mode of MODES) {
  test(`audit log has no axe violations in ${mode}`, async ({ page }) => {
    await actAsAuditor(page);
    await page.addInitScript((themeName) => {
      window.localStorage.setItem("ns.theme", JSON.stringify({ packId: "default", themeName }));
    }, mode);
    await page.goto(url(AUDIT_DOMAIN_FINANCE));
    await expect(page.getByTestId("audit-row").first()).toBeVisible();
    await page.waitForLoadState("networkidle");
    expect(await axeViolations(page)).toEqual([]);

    await page.getByTestId("audit-open").first().click();
    await expect(page.getByTestId("audit-drawer")).toBeVisible();
    expect(await axeViolations(page)).toEqual([]);
  });
}
