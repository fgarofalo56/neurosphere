import type { Page } from "@playwright/test";
import { expect, test } from "../../e2e-support/fixtures.ts";
import {
  EXPORT_AUDIT_ID,
  EXPORT_LIMIT_CASE_REF,
  INTERACTION_DOMAIN,
  INTERACTION_FAILED,
  INTERACTION_ID,
  SYNTHETIC_PROMPT,
} from "../../mock-api/features/interactions.ts";
import { axeViolations } from "../admin-sources/support.ts";

// PRP-104 item 6: the interaction explorer against the mock API (SYNTHETIC fixtures only). The
// stub session is the Viewer persona, which holds data.read in the fixture domain: it lists and
// inspects metadata but is refused content. The investigator persona is applied to the content
// and export calls only (the mock reads the role from the fake token suffix and stands in for the
// API's interaction.read / interaction.export checks).

const domain = encodeURIComponent(INTERACTION_DOMAIN);
const LIST = `/interactions?domain_id=${domain}`;
const OPEN = `${LIST}&interaction_id=${INTERACTION_ID}`;

async function actAsInvestigator(page: Page): Promise<void> {
  const token = "ns-e2e-fake-token.Investigator";
  const rewrite = (route: Parameters<Parameters<Page["route"]>[1]>[0]) =>
    route.continue({
      headers: { ...route.request().headers(), authorization: `Bearer ${token}` },
    });
  await page.route("**/content-reads", rewrite);
  await page.route("**/interaction-exports**", rewrite);
}

test("a viewer lists interactions, filters them and inspects one", async ({ page }) => {
  await page.goto(LIST);
  await expect(page.getByTestId("interaction-row")).toHaveCount(3);
  await page.getByLabel("Detected category").first().selectOption("email_address");
  await page.getByRole("button", { name: "Apply filters" }).click();
  await expect(page.getByTestId("interaction-row")).toHaveCount(1);

  await page.getByRole("link", { name: `Inspect interaction ${INTERACTION_ID}` }).click();
  const detail = page.getByTestId("interaction-detail");
  await expect(detail).toBeVisible();
  await expect(detail.getByTestId("coverage-label")).toHaveText(
    "Detection coverage: structured identifiers only",
  );
  await expect(detail.getByTestId("findings-list")).toContainText("email_address: 1 (replaced)");
  await expect(page.getByText(SYNTHETIC_PROMPT)).toHaveCount(0);
  expect(await axeViolations(page)).toEqual([]);
});

test("a viewer is told an investigator role is needed to reveal content", async ({ page }) => {
  await page.goto(OPEN);
  await page.getByRole("button", { name: "Reveal content" }).click();
  const dialog = page.getByRole("dialog");
  await dialog.getByLabel("Purpose").selectOption("incident_investigation");
  await dialog.getByRole("button", { name: "Reveal", exact: true }).click();
  const alert = dialog.getByTestId("reveal-forbidden");
  await expect(alert).toContainText("interaction_investigator");
  await expect(alert).toContainText("viewer assignment");
  await expect(page.getByText(SYNTHETIC_PROMPT)).toHaveCount(0);
});

test("an investigator states a purpose, reads the redacted content and closing discards it", async ({
  page,
}) => {
  await actAsInvestigator(page);
  await page.goto(OPEN);
  await page.getByRole("button", { name: "Reveal content" }).click();
  const dialog = page.getByRole("dialog");
  await dialog.getByRole("button", { name: "Reveal", exact: true }).click();
  await expect(dialog.getByText("Choose a purpose before continuing.")).toBeVisible();

  await dialog.getByLabel("Purpose").selectOption("policy_violation_review");
  await dialog.getByLabel("Case reference (optional)").fill("case-e2e-0001");
  const read = page.waitForRequest((r) => r.url().endsWith("/content-reads"));
  await dialog.getByRole("button", { name: "Reveal", exact: true }).click();
  expect((await read).postDataJSON()).toEqual({
    purpose_code: "policy_violation_review",
    case_ref: "case-e2e-0001",
  });
  await expect(dialog.getByText(SYNTHETIC_PROMPT)).toBeVisible();
  await expect(dialog.getByRole("heading", { name: "Redacted content" })).toBeFocused();
  expect(await axeViolations(page)).toEqual([]);

  await dialog.getByRole("button", { name: "Close" }).click();
  await expect(page.getByText(SYNTHETIC_PROMPT)).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Reveal content" })).toBeFocused();
});

test("reveal is disabled when nothing was stored", async ({ page }) => {
  await page.goto(`${LIST}&interaction_id=${INTERACTION_FAILED}`);
  await expect(page.getByTestId("interaction-detail")).toBeVisible();
  await expect(page.getByRole("button", { name: "Reveal content" })).toBeDisabled();
});

test("an investigator exports, sees the manifest and the 429 limit message", async ({ page }) => {
  await actAsInvestigator(page);
  await page.goto(LIST);
  await expect(page.getByTestId("interaction-row")).toHaveCount(3);
  await page.getByRole("button", { name: "Export content" }).click();
  const dialog = page.getByRole("dialog");
  await dialog.getByLabel("Purpose").selectOption("security_review");
  await dialog.getByTestId("export-from").fill("2026-10-01T00:00");
  await dialog.getByTestId("export-to").fill("2026-10-31T00:00");
  await dialog.getByRole("button", { name: "Create export" }).click();
  const manifest = dialog.getByTestId("export-manifest");
  await expect(manifest).toBeVisible();
  await expect(manifest.getByTestId("export-ids")).toHaveText("2");
  await expect(manifest.getByTestId("export-excluded")).toHaveText("1");
  await expect(manifest.getByTestId("export-held")).toHaveText("No");
  await expect(manifest.getByTestId("export-audit-id")).toHaveText(EXPORT_AUDIT_ID);
  const download = page.waitForEvent("download");
  await manifest.getByRole("button", { name: "Download bundle" }).click();
  expect((await download).suggestedFilename()).toMatch(/^interaction-export-.+\.json$/);
  await expect(manifest.getByTestId("export-downloaded")).toBeVisible();
  await dialog.getByRole("button", { name: "Close" }).click();

  await page.getByRole("button", { name: "Export content" }).click();
  const again = page.getByRole("dialog");
  await again.getByLabel("Purpose").selectOption("security_review");
  await again.getByLabel("Case reference (optional)").fill(EXPORT_LIMIT_CASE_REF);
  await again.getByTestId("export-from").fill("2026-10-01T00:00");
  await again.getByTestId("export-to").fill("2026-10-31T00:00");
  await again.getByRole("button", { name: "Create export" }).click();
  await expect(again.getByTestId("export-limit")).toContainText("in about 2 hours");
});

test("the explorer-off 503 shows the not-configured state, not an error", async ({ page }) => {
  await page.route("**/api/v1/domains/*/interactions?**", (route) =>
    route.fulfill({
      status: 503,
      contentType: "application/problem+json",
      json: {
        schema_version: "1.0.0",
        type: "https://neurosphere.invalid/problems/dependency-transient",
        title: "Dependency transient",
        status: 503,
        detail: "the interaction explorer is not configured",
        instance: "/api/v1/domains/x/interactions",
        code: "dependency_transient",
        reason: "interaction_explorer_unconfigured",
        retryable: false,
        correlation_id: "corr-e2e-off",
      },
    }),
  );
  await page.goto(LIST);
  await expect(page.getByTestId("explorer-unconfigured")).toContainText(
    "Interaction explorer not configured",
  );
  await expect(page.getByTestId("error-state")).toHaveCount(0);
});
