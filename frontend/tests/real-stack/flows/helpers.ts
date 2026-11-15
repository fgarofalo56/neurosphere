import { expect, type Page } from "@playwright/test";
import type { ApiAnswer } from "../fixtures.ts";

export const withDomain = (route: string, domain: string): string =>
  `${route}?domain_id=${encodeURIComponent(domain)}`;

/** Every readable data domain of the operator (the control-plane domain holds no data). */
export async function dataDomains(page: Page): Promise<string[]> {
  const answered = page.waitForResponse(
    (r) => r.url().includes("/api/v1/me/domains") && r.status() === 200,
  );
  await page.goto("/");
  const body = (await (await answered).json()) as { items: { domain_id: string }[] };
  const domains = body.items.map((i) => i.domain_id).filter((id) => !id.includes(":control"));
  expect(
    domains.length,
    "the operator reads no data domain; was the stack seeded?",
  ).toBeGreaterThan(0);
  return domains;
}

export async function firstDomain(page: Page): Promise<string> {
  return (await dataDomains(page))[0] ?? "";
}

/** Opens `route` in each readable domain until a `rows` test id is visible; returns that domain. */
export async function domainWithRows(page: Page, route: string, rows: string): Promise<string> {
  for (const domain of await dataDomains(page)) {
    await page.goto(withDomain(route, domain));
    await page.locator("main h1").first().waitFor();
    await page.locator(`[data-testid='${rows}'], [data-testid='empty-state']`).first().waitFor();
    if ((await page.getByTestId(rows).count()) > 0) return domain;
  }
  throw new Error(`no readable domain shows ${rows} on ${route}; was the stack seeded?`);
}

/** The newest answer whose path contains `fragment`; fails with the paths seen when none. */
export function answerFor(answers: readonly ApiAnswer[], fragment: string): ApiAnswer {
  const hit = [...answers].reverse().find((a) => a.path.includes(fragment));
  expect(
    hit,
    `no API answer for ${fragment}; saw ${answers.map((a) => a.path).join(", ")}`,
  ).toBeDefined();
  return hit as ApiAnswer;
}
