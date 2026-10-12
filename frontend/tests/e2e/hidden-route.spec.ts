import { expect, test } from "../e2e-support/fixtures.ts";

test("hidden workspace URL still hits the API, gets 403 and shows the forbidden state", async ({
  page,
}) => {
  // The stub session carries only the Viewer role, so Admin is not suggested in nav.
  const response = page.waitForResponse((r) => r.url().includes("/api/v1/workspaces/admin"));
  await page.goto("/workspaces/admin");
  const api = await response;
  expect(api.status()).toBe(403);
  const body = (await api.json()) as { code: string };
  expect(body.code).toBe("forbidden");

  await expect(page.getByText(/forbidden|not permitted|do not have access/i).first()).toBeVisible();
});
