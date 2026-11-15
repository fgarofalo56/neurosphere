import { expect, test } from "../fixtures.ts";
import { answerFor, domainWithRows } from "./helpers.ts";

/**
 * PRP-38 item 6 flow: the actions list shows the seeded intents, one opens, and the proposal form
 * loads. Read side only: nothing is proposed or executed (write flows belong to later PRPs).
 */
test("actions list and an intent detail answer from the seeded stack", async ({ visit }) => {
  const { page, answers } = visit;
  await domainWithRows(page, "/actions", "action-row");
  await expect(page.getByTestId("action-row").first()).toBeVisible();
  expect(answerFor(answers, "/intents").status).toBe(200);

  await page.locator("a[href^='/actions/detail']").first().click();
  await page.locator("main h1").first().waitFor();
  await expect.poll(() => answers.some((a) => /\/intents\/[^/]+$/.test(a.path))).toBe(true);
  const detail = [...answers].reverse().find((a) => /\/intents\/[^/]+$/.test(a.path));
  expect(detail?.status).toBe(200);
});
