import { expect, test } from "../e2e-support/fixtures.ts";
import { axeViolations } from "../helpers/axe.ts";

test.describe("smoke", () => {
  test("loads, signs in with the stub and renders the Viewer workspace", async ({ page }) => {
    const workspace = page.waitForResponse(
      (r) => r.url().includes("/api/v1/workspaces/viewer") && r.status() === 200,
    );
    await page.goto("/workspaces/viewer");
    await workspace;
    await expect(page.getByRole("main")).toBeVisible();
    await expect(page.getByRole("heading", { name: /viewer/i }).first()).toBeVisible();
  });

  test("home page has no axe violations", async ({ page }) => {
    await page.goto("/");
    await expect(page.getByRole("main")).toBeVisible();
    expect(await axeViolations(page)).toEqual([]);
  });
});
