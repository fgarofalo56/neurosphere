import { expect, test } from "../../e2e-support/fixtures.ts";
import {
  CAPTURE_APPROVAL_AUDIT_ID,
  CAPTURE_POLICY_ID,
} from "../../mock-api/features/capture.ts";
import { actAsAdmin, axeViolations } from "../admin-sources/support.ts";

// PRP-103 item 5: the read-only interaction capture page (synthetic mock data only).

test("an admin sees the policies, the off reason and the read-only note", async ({ page }) => {
  await actAsAdmin(page);
  await page.goto("/admin/capture");
  await expect(page.getByTestId("capture-policy-row")).toHaveCount(2);
  await expect(page.getByTestId("capture-off-reason")).toContainText(
    "The deployment-wide interaction capture setting is off.",
  );
  await expect(page.getByTestId("capture-change-note")).toContainText("capture_policy_change");
  await expect(page.getByTestId("capture-policy-counts")).toContainText("2 policies");

  await page.getByRole("button", { name: `View ${CAPTURE_POLICY_ID}` }).click();
  const detail = page.getByTestId("capture-policy-detail");
  await expect(detail).toBeVisible();
  await expect(detail.getByTestId("capture-detail-approval")).toHaveText(
    CAPTURE_APPROVAL_AUDIT_ID,
  );
  expect(await axeViolations(page)).toEqual([]);
  // Read-only: the page offers no change button.
  await expect(page.getByRole("button", { name: /create|edit|delete|activate/i })).toHaveCount(
    0,
  );
});

test("a viewer token gets the forbidden state", async ({ page }) => {
  await page.goto("/admin/capture");
  await expect(page.getByTestId("forbidden-state").first()).toBeVisible();
});
