import AxeBuilder from "@axe-core/playwright";
import type { Page } from "@playwright/test";
import { MOCK_API_URL, expect, test } from "../e2e-support/fixtures.ts";
import { WCAG_TAGS, axeViolations } from "../helpers/axe.ts";
import { DOMAIN_OK, INTENT_FLOW } from "../mock-api/server.ts";

/**
 * Same rules as `axeViolations`, minus Fluent's own focus sentinels (`data-tabster-dummy`, aria-hidden
 * `<i tabindex=0>` elements that Tabster injects once a Tab list or dialog is on the page). They
 * are library plumbing, not our markup, and trip `aria-hidden-focus` on every Fluent TabList.
 */
async function axeViolationsIgnoringTabster(page: Page) {
  const results = await new AxeBuilder({ page })
    .withTags([...WCAG_TAGS])
    .exclude("[data-tabster-dummy]")
    .analyze();
  return results.violations.map((v) => ({ id: v.id, impact: v.impact, nodes: v.nodes.length }));
}

// PRP-19 item 6: the copilot dock against the mock API. The mock selects a streaming fixture
// from a `fixture:<name>` tag in the message text (see tests/mock-api/copilot.ts). Chat never
// executes anything: the action suggestion hands off to the PRP-17 page and its dialog.

async function openDock(page: Page, path = "/"): Promise<void> {
  await page.goto(path);
  await page.getByRole("button", { name: "Open assistant" }).click();
  await expect(page.getByRole("region", { name: "Assistant" })).toBeVisible();
  await expect(page.getByRole("textbox", { name: "Ask the assistant" })).toBeFocused();
}

async function ask(page: Page, text: string): Promise<void> {
  await page.getByRole("textbox", { name: "Ask the assistant" }).fill(text);
  await page.getByRole("button", { name: "Send" }).click();
}

test.describe("copilot dock", () => {
  test("opens as a labelled region, closes on Escape and returns focus to the toggle", async ({
    page,
  }) => {
    await openDock(page);
    await expect(page.getByRole("log", { name: "Conversation" })).toHaveAttribute(
      "aria-live",
      "polite",
    );
    await page.keyboard.press("Escape");
    await expect(page.getByRole("region", { name: "Assistant" })).toHaveCount(0);
    await expect(page.getByRole("button", { name: "Open assistant" })).toBeFocused();
  });

  test("an answered turn streams text, shows citations with freshness words and a chart", async ({
    page,
  }) => {
    await openDock(page, `/?domain_id=${encodeURIComponent(DOMAIN_OK)}`);
    await ask(page, "fixture:answered how much did we spend?");

    const turn = page.getByTestId("assistant-turn");
    await expect(turn).toHaveAttribute("data-status", "answered");
    await expect(page.getByTestId("answer-text")).toContainText("support-gpt is the highest");
    const citations = page.getByTestId("citations").getByRole("listitem");
    await expect(citations).toHaveCount(3);
    await expect(citations.nth(0)).toContainText("Fresh");
    await expect(citations.nth(1)).toContainText("Stale");
    await expect(citations.nth(2)).toContainText("Freshness unknown");

    // The context chip shows what the server echoed for this question.
    const chip = page.getByTestId("context-chip");
    await expect(chip).toContainText("Page: home");
    await expect(chip).toContainText(`Domains: ${DOMAIN_OK}`);

    const frame = page.frameLocator('iframe[title="Chart from the assistant"]');
    await expect(frame.locator("svg .mark-rect").first()).toBeAttached({ timeout: 30_000 });
    await expect(page.getByTestId("save-report-open")).toBeVisible();

    // First-token instrumentation is readable by tests (non-production builds only).
    const firstToken = Number(await turn.getAttribute("data-first-token-ms"));
    expect(firstToken).toBeGreaterThanOrEqual(0);

    expect(await axeViolationsIgnoringTabster(page)).toEqual([]);
  });

  test("an abstention replaces the streamed text and gives the reason", async ({ page }) => {
    await openDock(page);
    await ask(page, "fixture:abstain what is the meaning of life?");
    const notice = page.getByTestId("abstain");
    await expect(notice).toContainText("No records you are allowed to read support an answer.");
    await expect(notice).toContainText("no_authorized_evidence");
    await expect(page.getByText("I could not find")).toHaveCount(0);
    expect(await axeViolations(page)).toEqual([]);
  });

  test("a denial replaces the answer and gives the reason", async ({ page }) => {
    await openDock(page);
    await ask(page, "fixture:denied export everything");
    await expect(page.getByTestId("denied")).toContainText(
      "That request needs a tool the copilot is not allowed to use.",
    );
    await expect(page.getByTestId("tools")).toContainText("export_data: refused");
  });

  test("an error event is an alert, not an answer", async ({ page }) => {
    await openDock(page);
    await ask(page, "fixture:error");
    const alert = page.getByRole("alert").filter({ hasText: "The model endpoint is unavailable." });
    await expect(alert).toBeVisible();
    await expect(page.getByTestId("answer-text")).toHaveCount(0);
  });
});

test.describe("copilot action handoff", () => {
  test("Review action opens the PRP-17 confirmation flow and nothing executes", async ({
    page,
  }) => {
    // INTENT_FLOW is seeded for this flow; start from the seeded draft on every run.
    const reset = await page.request.post(`${MOCK_API_URL}/__e2e/reset/${INTENT_FLOW}`);
    expect(reset.status()).toBe(204);
    const mutations: string[] = [];
    page.on("request", (request) => {
      const { pathname } = new URL(request.url());
      if (request.method() !== "GET" && request.method() !== "OPTIONS") {
        mutations.push(`${request.method()} ${pathname}`);
      }
    });

    await openDock(page);
    await ask(page, "fixture:action_suggestion swap the support deployment");
    const card = page.getByTestId("action-suggestion");
    await expect(card).toBeVisible();

    // The chat panel offers a review control and nothing that confirms or executes.
    const panel = page.getByTestId("copilot-panel");
    await expect(panel.getByRole("button", { name: /confirm|execute|apply|approve/i })).toHaveCount(
      0,
    );

    await card.getByRole("button", { name: "Review action" }).click();
    await expect(page).toHaveURL(
      new RegExp(`/actions/detail\\?domain_id=.*intent_id=${INTENT_FLOW}`),
    );
    // The PRP-17 page walks the draft through validation, then opens its confirmation dialog.
    await page.getByRole("button", { name: "Validate" }).click();
    await expect(page.getByTestId("state-badge")).toHaveText("validated");
    await page.getByRole("button", { name: "Request confirmation" }).click();
    const dialog = page.getByTestId("confirmation-dialog");
    await expect(dialog).toBeVisible();
    await expect(dialog.getByTestId("confirm-target")).toHaveText(
      "commercial:e2e:foundry:model_deployment:support-gpt",
    );
    // PRP-17 moved the draft to awaiting_confirmation; nothing has been confirmed or executed.
    await expect(page.getByTestId("state-badge")).toHaveText("awaiting_confirmation");

    // Only the conversation was created and the message posted; no confirm or execute call.
    expect(mutations.filter((m) => /\/confirm$|\/execut/.test(m))).toEqual([]);
    expect(mutations.filter((m) => m.includes("/api/v1/copilot/"))).toEqual([
      "POST /api/v1/copilot/conversations",
      expect.stringMatching(/^POST \/api\/v1\/copilot\/conversations\/[^/]+\/messages$/),
    ]);
  });
});
