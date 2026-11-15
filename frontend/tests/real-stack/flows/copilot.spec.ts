import { expect, test } from "../fixtures.ts";
import { answerFor, firstDomain } from "./helpers.ts";

/**
 * PRP-38 item 6 flow: the copilot is disabled by default in the real stack (no model deployment
 * is configured; PRP-19). The dock must say so, and the API must answer the typed
 * `copilot_unconfigured` 503 for a conversation list, never a 500 and never a silent success.
 */
test("copilot dock reports not configured and the API answers the typed 503", async ({ visit }) => {
  const { page, answers } = visit;
  await firstDomain(page);

  await page.getByTestId("copilot-toggle").click();
  await expect(page.getByTestId("copilot-panel")).toBeVisible();
  await expect(page.getByTestId("copilot-not-configured")).toBeVisible();
  expect(answerFor(answers, "/api/v1/copilot/status").status).toBe(200);

  const probe = await page.evaluate(async () => {
    const entries = Object.entries(window.sessionStorage);
    const raw = entries.find(([key]) => key.includes("accesstoken"))?.[1] ?? "{}";
    const secret = (JSON.parse(raw) as { secret?: string }).secret ?? "";
    const response = await fetch("/api/v1/copilot/conversations", {
      headers: { Authorization: `Bearer ${secret}` },
    });
    return { status: response.status, body: (await response.json()) as { reason?: string } };
  });
  expect(probe.status).toBe(503);
  expect(probe.body.reason).toBe("copilot_unconfigured");
});
