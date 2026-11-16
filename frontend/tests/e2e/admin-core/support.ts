import AxeBuilder from "@axe-core/playwright";
import type { Page } from "@playwright/test";
import { WCAG_TAGS } from "../../helpers/axe.ts";

/**
 * PRP-53 e2e support. The stub session carries the Viewer role and the mock API reads the caller's
 * role from the fake token suffix (stubMsal.ts), so a spec that needs another persona rewrites
 * the bearer on every API call, as the audit and a11y specs do. The mock stands in for the API's
 * permission checks; nothing here decides access.
 */
export async function actAs(page: Page, persona: "Admin" | "Auditor"): Promise<void> {
  const token = `ns-e2e-fake-token.${persona}`;
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

/** A reason code the API accepts (lower-case snake case). */
export const REASON = "e2e_change";
