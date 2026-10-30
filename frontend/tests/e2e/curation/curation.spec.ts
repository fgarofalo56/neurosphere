import AxeBuilder from "@axe-core/playwright";
import type { Page } from "@playwright/test";
import { expect, test } from "../../e2e-support/fixtures.ts";
import { WCAG_TAGS } from "../../helpers/axe.ts";
import { DOMAIN_OK } from "../../mock-api/server.ts";

// PRP-31 item 4: relationship curation against the mock API. The stub session is a Viewer, so the
// spec swaps the bearer token per call, the way mcp-admin.spec.ts does: the mock stands in for the
// API's catalog.curate and evidence.read checks. The page never decides anything.

const STEWARD = "ns-e2e-fake-token.Steward";
const AUDITOR = "ns-e2e-fake-token.Auditor";

function edgeUrl(edgeId: string): string {
  const q = new URLSearchParams({ edge_id: edgeId, domain_id: DOMAIN_OK });
  return `/catalog/edge?${q.toString()}`;
}

/** Grants catalog.curate on the Finance domain in the domain list, and picks the persona per call. */
async function actAs(page: Page, token: string): Promise<void> {
  await page.route("**/api/v1/me/domains", async (route) => {
    const response = await route.fetch();
    const body = (await response.json()) as {
      items: { domain_id: string; permissions: string[] }[];
    };
    for (const item of body.items) {
      if (item.domain_id === DOMAIN_OK) item.permissions = [...item.permissions, "catalog.curate"];
    }
    await route.fulfill({ response, json: body });
  });
  await page.route("**/api/v1/catalog/**", (route) =>
    route.continue({
      headers: { ...route.request().headers(), authorization: `Bearer ${token}` },
    }),
  );
}

async function axeBlocking(page: Page) {
  const results = await new AxeBuilder({ page })
    .withTags([...WCAG_TAGS])
    .exclude("[data-tabster-dummy]")
    .analyze();
  return results.violations
    .filter((v) => v.impact === "serious" || v.impact === "critical")
    .map((v) => ({
      id: v.id,
      impact: v.impact,
      nodes: v.nodes.length,
      targets: v.nodes.map((n) => n.target.join(" ")),
    }));
}

test("lock with a future expiry is accepted (201) and the edge reloads locked", async ({
  page,
}) => {
  await actAs(page, STEWARD);
  const edgeId = "commercial:e2e:edge:lock-agent/uses/lock-model";
  await page.goto(edgeUrl(edgeId));
  await expect(page.getByTestId("edge-id")).toHaveText(edgeId);
  await expect(page.getByTestId("security-evidence-ids")).toBeVisible();

  await page.getByRole("button", { name: "Lock", exact: true }).click();
  const dialog = page.getByTestId("change-confirm-dialog");
  await expect(dialog.getByTestId("change-target")).toHaveText(edgeId);
  await dialog.getByRole("textbox", { name: /reason/i }).fill("freeze for the quarterly review");
  await dialog.getByLabel(/expiry/i).fill("2099-01-01T10:00");
  const response = page.waitForResponse((r) => r.request().method() === "POST");
  await dialog.getByRole("button", { name: "Confirm change" }).click();
  const decided = await response;
  expect(decided.status()).toBe(201);
  const sent = decided.request().postDataJSON() as Record<string, unknown>;
  expect(Object.keys(sent).sort()).toEqual(
    ["decision", "expected_edge_etag", "expected_edge_version", "lock_expiry", "reason"].sort(),
  );
  expect(decided.url()).toContain(encodeURIComponent(DOMAIN_OK));
  await expect(page.getByTestId("decision-notice")).toBeVisible();
  await expect(page.getByTestId("edge-lock")).toContainText("Locked");
  await expect(page.getByRole("button", { name: "Unlock" })).toBeVisible();
});

test("a stale edge is surfaced with a reload action and is not retried", async ({ page }) => {
  await actAs(page, STEWARD);
  await page.goto(edgeUrl("commercial:e2e:edge:stale-edge/uses/model"));
  await page.getByRole("button", { name: "Accept", exact: true }).click();
  const dialog = page.getByTestId("change-confirm-dialog");
  await dialog.getByRole("textbox", { name: /reason/i }).fill("looks right");
  let posts = 0;
  page.on("request", (r) => {
    if (r.method() === "POST") posts += 1;
  });
  await dialog.getByRole("button", { name: "Confirm change" }).click();
  await expect(dialog.getByTestId("decision-error")).toContainText("changed since you opened it");
  await expect(dialog.getByRole("button", { name: "Reload edge" })).toBeVisible();
  expect(posts).toBe(1);
});

test("observations show for evidence holders and a 403 reads 'need evidence access' for others", async ({
  page,
}) => {
  await actAs(page, AUDITOR);
  const edgeId = "commercial:e2e:edge:obs-agent/uses/obs-model";
  await page.goto(edgeUrl(edgeId));
  await page.getByRole("tab", { name: "Observations" }).click();
  await expect(page.getByTestId("observations")).toBeVisible();
  await page.getByRole("button", { name: "Load more observations" }).click();
  await expect(page.getByRole("row")).toHaveCount(4);

  await page.unroute("**/api/v1/catalog/**");
  await page.route("**/api/v1/catalog/**", (route) =>
    route.continue({
      headers: {
        ...route.request().headers(),
        authorization: "Bearer ns-e2e-fake-token.Viewer",
      },
    }),
  );
  await page.reload();
  await page.getByRole("tab", { name: "Observations" }).click();
  await expect(page.getByText("Observations need evidence access")).toBeVisible();
  await expect(page.getByTestId("observations")).toHaveCount(0);
});

for (const mode of ["light", "dark", "high-contrast"] as const) {
  test(`axe: curation page in ${mode} has no serious or critical violations`, async ({ page }) => {
    await page.addInitScript((m) => {
      window.localStorage.setItem("ns.theme", JSON.stringify({ packId: "default", themeName: m }));
    }, mode);
    await actAs(page, STEWARD);
    await page.goto(edgeUrl("commercial:e2e:edge:axe-agent/uses/axe-model"));
    await expect(page.getByTestId("edge-summary")).toBeVisible();
    await page.waitForLoadState("networkidle");
    expect(await axeBlocking(page)).toEqual([]);
    await page.getByRole("button", { name: "Override", exact: true }).click();
    await expect(page.getByTestId("change-confirm-dialog")).toBeVisible();
    // Let the dialog's open animation finish: axe measures colour mid-fade otherwise.
    await page.waitForTimeout(600);
    expect(await axeBlocking(page)).toEqual([]);
  });
}
