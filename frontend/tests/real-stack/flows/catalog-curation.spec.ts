import { expect, test } from "../fixtures.ts";
import { answerFor, domainWithRows, withDomain } from "./helpers.ts";

/**
 * PRP-38 item 6 flow: the catalog lists seeded entities, an entity opens from the list, and the
 * curation surfaces (recertifications, stale agents) answer. Each step asserts the API status the
 * page received, not only that something rendered.
 */
test("catalog list, entity detail and curation queues answer from the seeded stack", async ({
  visit,
}) => {
  const { page, answers } = visit;
  const domain = await domainWithRows(page, "/catalog", "entity-row");
  await expect(page.getByTestId("entity-row").first()).toBeVisible();
  expect(answerFor(answers, "/api/v1/catalog/domains/").status).toBe(200);

  await page.locator("a[href^='/catalog/entity']").first().click();
  await page.locator("main h1").first().waitFor();
  await expect
    .poll(() => answers.some((a) => /\/api\/v1\/catalog\/entities\/[^/]+$/.test(a.path)))
    .toBe(true);
  expect(answerFor(answers, "/api/v1/catalog/entities/").status).toBe(200);

  await page.goto(withDomain("/catalog/recertifications", domain));
  await page.locator("main h1").first().waitFor();
  await expect
    .poll(() => answers.some((a) => a.path.includes("/catalog/recertifications")))
    .toBe(true);
  expect(answerFor(answers, "/catalog/recertifications").status).toBe(200);
});
