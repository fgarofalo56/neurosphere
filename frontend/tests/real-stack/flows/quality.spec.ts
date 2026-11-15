import { expect, test } from "../fixtures.ts";
import { answerFor, firstDomain, withDomain } from "./helpers.ts";

/** PRP-38 item 6 flow: the quality page reads the evaluation quality answer for a seeded domain. */
test("quality page is served by the evaluation quality API", async ({ visit }) => {
  const { page, answers } = visit;
  const domain = await firstDomain(page);

  await page.goto(withDomain("/quality", domain));
  await page.locator("main h1").first().waitFor();
  await expect
    .poll(() => answers.some((a) => a.path.includes("/api/v1/evaluation/domains/")))
    .toBe(true);
  const answer = answerFor(answers, "/api/v1/evaluation/domains/");
  expect(answer.status).toBe(200);
  expect(answer.path).toContain("/quality");
  await expect(page.getByText(/demo/i)).toHaveCount(0);
});
