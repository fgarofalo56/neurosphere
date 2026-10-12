import AxeBuilder from "@axe-core/playwright";
import type { Page } from "@playwright/test";
import { axe } from "vitest-axe";

/** WCAG 2.x A/AA rule tags (NS-10 targets WCAG 2.2 AA plus Section 508). */
export const WCAG_TAGS = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"] as const;

export interface AxeViolationSummary {
  readonly id: string;
  readonly impact: string | null | undefined;
  readonly nodes: number;
}

/** Playwright: run axe against the current page and return a compact violation list. */
export async function axeViolations(page: Page): Promise<AxeViolationSummary[]> {
  const results = await new AxeBuilder({ page }).withTags([...WCAG_TAGS]).analyze();
  return results.violations.map((v) => ({ id: v.id, impact: v.impact, nodes: v.nodes.length }));
}

/**
 * Vitest (jsdom): run axe on a rendered container; use with
 * `expect(await axeViolationsFor(container)).toHaveNoViolations()`.
 * jsdom has no layout, so colour-contrast is disabled here and covered by Playwright.
 */
export function axeViolationsFor(container: Element) {
  return axe(container, { rules: { "color-contrast": { enabled: false } } });
}
