import { expect, test } from "../e2e-support/fixtures.ts";
import {
  NOTIFICATION_CHANNEL_ID,
  NOTIFICATION_FLAKY_CHANNEL_ID,
} from "../mock-api/features/notifications.ts";
import { actAsAdmin, axeViolations } from "./admin-sources/support.ts";

// PRP-107 item 7: notification channels, subscriptions and deliveries (synthetic mock data only).
// The mock keeps state across a run, so each test uses its own ids and none depends on order.

test("an admin sees channels with delivery counts and the last error", async ({ page }) => {
  await actAsAdmin(page);
  await page.goto("/admin/notifications");
  await expect(page.getByTestId("channel-row")).toHaveCount(3);
  const ops = page.getByTestId("channel-row").filter({ hasText: NOTIFICATION_CHANNEL_ID });
  await expect(ops.getByTestId("channel-counts")).toContainText("delivered 2");
  const flaky = page.getByTestId("channel-row").filter({ hasText: NOTIFICATION_FLAKY_CHANNEL_ID });
  await expect(flaky).toContainText("http_500");
  expect(await axeViolations(page)).toEqual([]);
});

test("a test send shows its outcome through the confirm dialog", async ({ page }) => {
  await actAsAdmin(page);
  await page.goto("/admin/notifications");
  await page.getByRole("button", { name: `Send test to ${NOTIFICATION_FLAKY_CHANNEL_ID}` }).click();
  await page.getByRole("button", { name: "Confirm change" }).click();
  await expect(page.getByTestId("test-result")).toContainText("failed: http_500 (HTTP 500)");
});

test("create offers not_built kinds disabled and refuses a raw secret", async ({ page }) => {
  await actAsAdmin(page);
  await page.goto("/admin/notifications");
  await page.getByRole("button", { name: "New channel" }).click();
  await expect(page.getByRole("option", { name: /^email: not built/ })).toBeDisabled();
  await page.getByLabel(/^Channel id/).fill("e2e-created");
  await page.getByLabel(/^Display name/).fill("E2E created");
  await page.getByLabel(/^Allowed host/).fill("hooks.example.org");
  await page.getByLabel(/^Endpoint secret/).fill("plain-secret-value");
  await page
    .getByLabel(/^Signing secret/)
    .fill("https://kv-e2e.vault.azure.net/secrets/e2e-signing");
  await page.getByRole("button", { name: "Review change" }).click();
  await expect(page.getByText("Not a Key Vault secret reference")).toBeVisible();
  await page
    .getByLabel(/^Endpoint secret/)
    .fill("https://kv-e2e.vault.azure.net/secrets/e2e-endpoint");
  await page.getByRole("button", { name: "Review change" }).click();
  await page.getByRole("button", { name: "Confirm change" }).click();
  await expect(page.getByTestId("channel-row").filter({ hasText: "e2e-created" })).toBeVisible();
});

test("the API refusal reason is shown when the host is not allowed", async ({ page }) => {
  await actAsAdmin(page);
  await page.goto("/admin/notifications");
  await page.getByRole("button", { name: "New channel" }).click();
  await page.getByLabel(/^Channel id/).fill("e2e-blocked");
  await page.getByLabel(/^Display name/).fill("Blocked");
  await page.getByLabel(/^Allowed host/).fill("blocked.example.net");
  await page
    .getByLabel(/^Endpoint secret/)
    .fill("https://kv-e2e.vault.azure.net/secrets/b-endpoint");
  await page.getByLabel(/^Signing secret/).fill("https://kv-e2e.vault.azure.net/secrets/b-signing");
  await page.getByRole("button", { name: "Review change" }).click();
  await page.getByRole("button", { name: "Confirm change" }).click();
  await expect(page.getByTestId("notification-error")).toContainText("host_not_allowed");
});

test("subscriptions and deliveries tabs list their rows and filter deliveries", async ({
  page,
}) => {
  await actAsAdmin(page);
  await page.goto("/admin/notifications");
  await page.getByRole("tab", { name: "Subscriptions" }).click();
  await expect(page.getByTestId("subscription-row").first()).toContainText("hitl_item_assigned");
  await page.getByRole("tab", { name: "Deliveries" }).click();
  await expect(page.getByTestId("delivery-row")).toHaveCount(4);
  await page.getByLabel("Status filter").selectOption("failed");
  await expect(page.getByTestId("delivery-row")).toHaveCount(1);
  expect(await axeViolations(page)).toEqual([]);
});

test("a viewer token gets the forbidden state", async ({ page }) => {
  await page.goto("/admin/notifications");
  await expect(page.getByTestId("forbidden-state").first()).toBeVisible();
});
