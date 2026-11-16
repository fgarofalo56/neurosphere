import AxeBuilder from "@axe-core/playwright";
import type { Page } from "@playwright/test";
import { WCAG_TAGS } from "../../helpers/axe.ts";

/**
 * PRP-57 e2e support. The stub session carries the Viewer role and the mock API reads the
 * caller's role from the fake token suffix, so a spec that needs the Admin persona rewrites the
 * bearer on every API call (as the admin-core specs do). The mock stands in for the API's
 * permission checks; nothing here decides access. Mock state is module-level in the mock server
 * process, so these specs use distinct ids and do not depend on running order.
 */
export async function actAsAdmin(page: Page): Promise<void> {
  const token = "ns-e2e-fake-token.Admin";
  await page.route("**/api/v1/**", (route) =>
    route.continue({
      headers: { ...route.request().headers(), authorization: `Bearer ${token}` },
    }),
  );
}

export async function axeViolations(page: Page) {
  const results = await new AxeBuilder({ page })
    .withTags([...WCAG_TAGS])
    .exclude("[data-tabster-dummy]")
    .analyze();
  return results.violations.map((v) => ({ id: v.id, impact: v.impact, nodes: v.nodes.length }));
}
