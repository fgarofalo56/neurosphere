import { expect, test } from "../../e2e-support/fixtures.ts";
import { MOCK_API_URL } from "../../e2e-support/fixtures.ts";
import { axeViolations } from "../../helpers/axe.ts";
import {
  DOMAIN_FORBIDDEN,
  DOMAIN_OK,
  FAKE_TOKEN_PREFIX,
  RECOMMENDATION_NEXT_CURSOR,
  RECOMMENDATION_PRICE_VERSION,
  RECOMMENDATION_REVIEW_ID,
  REC_COST_SPIKE,
  REC_DUPLICATE,
  REC_RIGHT_SIZING,
  REC_UNUSED,
} from "../../mock-api/server.ts";

// PRP-15 item 6: the recommendations list and detail through the stubbed sign-in against the mock
// API. The domain rides in the APP url (`domain_id`) and in the API PATH. Recommendations are
// advisory: no control executes, applies or merges anything.

function listUrl(domain: string, extra = ""): string {
  return `/recommendations?domain_id=${encodeURIComponent(domain)}${extra}`;
}

function detailUrl(domain: string, id: string): string {
  return `/recommendations/detail?domain_id=${encodeURIComponent(domain)}&recommendation_id=${encodeURIComponent(id)}`;
}

test.describe("list", () => {
  test("lists recommendations with owner and advisory status, and pages by cursor", async ({
    page,
  }) => {
    const api = page.waitForResponse(
      (r) => r.url().includes("/api/v1/recommendations/domains/") && r.status() === 200,
    );
    await page.goto(listUrl(DOMAIN_OK));
    const response = await api;
    expect(new URL(response.url()).pathname).toBe(
      `/api/v1/recommendations/domains/${encodeURIComponent(DOMAIN_OK)}`,
    );
    expect(new URL(response.url()).searchParams.has("domain_id")).toBe(false);

    const rows = page.getByTestId("recommendation-row");
    await expect(rows).toHaveCount(3);
    await expect(rows.first().getByTestId("advisory-badge")).toHaveText("Advisory");
    // Unresolved owner renders "unknown", not an empty cell.
    await expect(
      rows.filter({ hasText: "Unused agent" }).getByText("unknown", { exact: true }),
    ).toBeVisible();

    const next = page.waitForResponse((r) =>
      r.url().includes(`cursor=${RECOMMENDATION_NEXT_CURSOR}`),
    );
    await page.getByRole("button", { name: "Next page" }).click();
    await next;
    await expect(rows).toHaveCount(1);
    await expect(rows.first()).toContainText("Candidate duplicate");
  });

  test("kind filter narrows the list", async ({ page }) => {
    await page.goto(listUrl(DOMAIN_OK, "&kind=unused_agent"));
    const rows = page.getByTestId("recommendation-row");
    await expect(rows).toHaveCount(1);
    await expect(rows.first()).toContainText("Unused agent");
  });

  test("has no axe violations", async ({ page }) => {
    await page.goto(listUrl(DOMAIN_OK));
    await expect(page.getByTestId("recommendation-row").first()).toBeVisible();
    expect(await axeViolations(page)).toEqual([]);
  });

  test("a forbidden domain shows the forbidden state, not an empty list", async ({ page }) => {
    const api = page.waitForResponse((r) => r.url().includes("/api/v1/recommendations/domains/"));
    await page.goto(listUrl(DOMAIN_FORBIDDEN));
    expect((await api).status()).toBe(403);
    await expect(page.getByTestId("forbidden-state")).toBeVisible();
    await expect(page.getByTestId("recommendation-row")).toHaveCount(0);
    await expect(page.getByTestId("empty-state")).toHaveCount(0);
  });

  test("the list is keyboard reachable: a row link opens the detail", async ({ page }) => {
    await page.goto(listUrl(DOMAIN_OK));
    const link = page.getByRole("link", { name: "Model right-sizing" });
    await expect(link).toBeVisible();
    await link.focus();
    await expect(link).toBeFocused();
    await page.keyboard.press("Enter");
    await expect(page.getByRole("heading", { level: 1, name: "Model right-sizing" })).toBeVisible();
  });
});

test.describe("detail", () => {
  test("shows evidence window, coverage, uncertainty, prerequisites, estimate, owner", async ({
    page,
  }) => {
    await page.goto(detailUrl(DOMAIN_OK, REC_RIGHT_SIZING));
    await expect(page.getByTestId("advisory-badge")).toHaveText("Advisory");
    await expect(page.getByTestId("advisory-reason")).toContainText("action gates not passed");
    await expect(page.getByTestId("evidence-window")).toContainText("2026-10-03T00:00:00Z");
    await expect(page.getByTestId("evidence-window")).toContainText("2026-10-10T00:00:00Z");
    await expect(page.getByTestId("coverage")).toContainText("observed 60%");
    await expect(page.getByTestId("uncertainty")).toHaveText("not estimable");
    await expect(page.getByTestId("prerequisites")).toContainText("quality_regression_test: unmet");
    await expect(page.getByRole("heading", { name: "Estimate", level: 2 })).toBeVisible();
    await expect(page.getByTestId("estimate")).toContainText("1210.50 USD");
    await expect(page.getByTestId("price-version")).toContainText(
      `price version ${RECOMMENDATION_PRICE_VERSION} (effective 2026-10-01)`,
    );
    await expect(page.getByTestId("owner")).toContainText("team-support (inferred)");
    // Evidence is insufficient: no fabricated score.
    await expect(page.getByTestId("insufficient-history")).toBeVisible();
    await expect(page.getByTestId("score")).toHaveCount(0);
  });

  test("missing fields render unknown, never 0 or blank", async ({ page }) => {
    await page.goto(detailUrl(DOMAIN_OK, REC_UNUSED));
    await expect(page.getByTestId("coverage")).toContainText("observed unknown");
    await expect(page.getByTestId("owner")).toHaveText("unknown");
    await expect(page.getByTestId("estimate-unknown")).toContainText("unknown");
    await expect(page.getByTestId("prerequisites-empty")).toHaveText("unknown");
    await expect(page.getByTestId("generator")).toHaveText("unknown");
  });

  test("a duplicate candidate says consolidation review only", async ({ page }) => {
    await page.goto(detailUrl(DOMAIN_OK, REC_DUPLICATE));
    await expect(page.getByTestId("duplicate-note")).toContainText("never merged automatically");
  });

  test("has no execute, apply or merge control, only route to review", async ({ page }) => {
    await page.goto(detailUrl(DOMAIN_OK, REC_RIGHT_SIZING));
    await expect(page.getByRole("button", { name: "Route to review" })).toBeVisible();
    await expect(
      page.getByRole("button", { name: /execute|apply|merge|swap|deploy|delete/i }),
    ).toHaveCount(0);
  });

  test("has no axe violations", async ({ page }) => {
    await page.goto(detailUrl(DOMAIN_OK, REC_RIGHT_SIZING));
    await expect(page.getByTestId("estimate")).toBeVisible();
    expect(await axeViolations(page)).toEqual([]);
  });

  test("a forbidden domain shows the forbidden state", async ({ page }) => {
    const api = page.waitForResponse((r) => r.url().includes("/items/"));
    await page.goto(detailUrl(DOMAIN_FORBIDDEN, REC_RIGHT_SIZING));
    expect((await api).status()).toBe(403);
    await expect(page.getByTestId("forbidden-state")).toBeVisible();
  });
});

test.describe("route to review", () => {
  test("routing by keyboard shows Pending review with the request id", async ({ page }) => {
    await page.goto(detailUrl(DOMAIN_OK, REC_COST_SPIKE));
    const button = page.getByRole("button", { name: "Route to review" });
    // A reused local mock server may already hold the routed state; CI starts fresh.
    await expect(button.or(page.getByTestId("review-state"))).toBeVisible();
    if ((await button.count()) > 0) {
      const post = page.waitForResponse(
        (r) => r.url().includes("/review-requests") && r.request().method() === "POST",
      );
      await button.focus();
      await expect(button).toBeFocused();
      await page.keyboard.press("Enter");
      expect((await post).status()).toBe(202);
    }
    await expect(page.getByTestId("review-state")).toContainText("Pending review");
    await expect(page.getByTestId("review-request-id")).toHaveText(RECOMMENDATION_REVIEW_ID);
    // Still no executable state after routing.
    await expect(page.getByRole("button", { name: /execute|apply|merge/i })).toHaveCount(0);
  });
});

test.describe("API refuses execution", () => {
  const headers = { authorization: `Bearer ${FAKE_TOKEN_PREFIX}Steward` };
  const base = `${MOCK_API_URL}/api/v1/recommendations/domains/${encodeURIComponent(DOMAIN_OK)}`;

  test("executions answer 409 capability_unavailable", async ({ request }) => {
    const res = await request.post(`${base}/executions`, { headers, data: {} });
    expect(res.status()).toBe(409);
    const body = (await res.json()) as { code: string; detail: string };
    expect(body.code).toBe("capability_unavailable");
    expect(body.detail).toBe("action gates not passed");
  });

  test("an out-of-scope domain answers 403 on every recommendations route", async ({ request }) => {
    const other = `${MOCK_API_URL}/api/v1/recommendations/domains/${encodeURIComponent(DOMAIN_FORBIDDEN)}`;
    expect((await request.get(other, { headers })).status()).toBe(403);
    expect(
      (await request.get(`${other}/items/${encodeURIComponent(REC_UNUSED)}`, { headers })).status(),
    ).toBe(403);
    expect((await request.post(`${other}/executions`, { headers, data: {} })).status()).toBe(403);
  });
});

test("navigation lists the recommendations entry", async ({ page }) => {
  await page.goto("/");
  const nav = page.getByRole("navigation", { name: "Primary" });
  await expect(nav.getByRole("link", { name: "Recommendations" })).toBeVisible();
});
