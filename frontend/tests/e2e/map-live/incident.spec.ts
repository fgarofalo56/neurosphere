import type { Page } from "@playwright/test";
import { expect, test } from "../../e2e-support/fixtures.ts";
import {
  INCIDENT_IDS as I,
  control,
  incidentDomain,
  mapUrl,
  openLiveMap,
  searchAndSelect,
  sendHealthDelta,
} from "./support.ts";

// PRP-77 item 6, story: during an incident the SRE selects the failing service and sees every
// dependent by depth, as a text list with health and as a ring plus enlarged node on the canvas,
// and the view follows live health changes without a click. Health flips are driven two ways at
// once, like production: the mock control route changes what the API answers and the fake gateway
// pushes the matching `delta`.

// The impact view recomputes after a 2 s quiet period (IMPACT_RECOMPUTE_MS); allow for it.
const RECOMPUTE_TIMEOUT = 15_000;

/** Display size of a node on the canvas (an affected node is drawn 1.4 times larger). */
function nodeSize(page: Page, id: string): Promise<number> {
  return page.evaluate((nodeId) => {
    const el = document.querySelector('[data-testid="map-canvas"]') as HTMLElement & {
      __nsMap?: { sigma: { getNodeDisplayData(id: string): { size: number } | undefined } };
    };
    return el.__nsMap?.sigma.getNodeDisplayData(nodeId)?.size ?? 0;
  }, id);
}

async function showImpactFor(page: Page, search: string, label: string): Promise<void> {
  await searchAndSelect(page, search, label);
  await expect(page.getByTestId("panel-label")).toHaveText(label);
  await page.getByTestId("show-impact").click();
  await expect(page.getByTestId("impact-panel")).toBeVisible();
}

test.describe("map incident view", () => {
  test("lists dependents by depth with health as text and highlights them on the canvas", async ({
    page,
  }) => {
    await openLiveMap(page, mapUrl(incidentDomain("impact")));
    const idle = {
      billing: await nodeSize(page, I.billing),
      tax: await nodeSize(page, I.tax),
    };

    const request = page.waitForRequest(
      (r) => r.method() === "POST" && r.url().includes("/impact"),
    );
    await showImpactFor(page, "ledger", "ledger-service");
    expect((await request).postDataJSON()).toEqual({ node_id: I.ledger, max_depth: 2 });

    await expect(page.getByTestId("impact-status")).toHaveText(
      "5 dependents affected by ledger-service",
    );
    const list = page.getByTestId("impact-list");
    const depth1 = page.getByTestId("impact-depth-1");
    const depth2 = page.getByTestId("impact-depth-2");
    await expect(depth1).toContainText("Depth 1");
    await expect(depth1.getByTestId("impact-row")).toHaveText([
      "billing-agent, Agent, health Healthy",
      "refund-agent, Agent, health Healthy",
    ]);
    await expect(depth2.getByTestId("impact-row")).toHaveText([
      "reconcile-sub-agent, Sub-agent, health Healthy",
      "report-agent, Agent, health Healthy",
      "archive-agent, Agent, health Healthy",
    ]);
    await expect(list).not.toContainText("tax-tool");
    // The archive agent is a dependent that is not on the map: it is also listed apart, with an action.
    const offscreen = page.getByTestId("impact-offscreen-row");
    await expect(offscreen).toHaveCount(1);
    await expect(offscreen).toContainText("archive-agent, Agent, health Healthy");

    // Canvas: dependents are drawn larger (and ringed); a node that does not depend on the
    // service keeps its size.
    await expect.poll(() => nodeSize(page, I.billing)).toBeGreaterThan(idle.billing * 1.2);
    expect(await nodeSize(page, I.tax)).toBeCloseTo(idle.tax, 5);

    // The depth control re-asks the server.
    const narrower = page.waitForRequest(
      (r) =>
        r.method() === "POST" &&
        r.url().includes("/impact") &&
        r.postData()?.includes('"max_depth":1') === true,
    );
    await page.getByTestId("impact-depth").selectOption("1");
    await narrower;
    await expect(page.getByTestId("impact-status")).toHaveText(
      "2 dependents affected by ledger-service",
    );
    await expect(page.getByTestId("impact-depth-2")).toHaveCount(0);

    // Clearing restores the previous view.
    await page.getByTestId("impact-clear").click();
    await expect(page.getByTestId("impact-panel")).toHaveCount(0);
    await expect.poll(() => nodeSize(page, I.billing)).toBeCloseTo(idle.billing, 5);
  });

  test("shows an off-screen dependent on the map and toggles with the keyboard shortcut", async ({
    page,
  }) => {
    await openLiveMap(page, mapUrl(incidentDomain("offscreen")));
    await showImpactFor(page, "ledger", "ledger-service");
    await expect(page.getByTestId("impact-offscreen-row")).toHaveCount(1);

    const neighbourhood = page.waitForResponse(
      (r) => r.url().includes(`/neighborhood/${encodeURIComponent(I.archive)}`) && r.ok(),
    );
    await page.getByRole("button", { name: "Show archive-agent on map" }).click();
    await neighbourhood;
    await expect(page.getByTestId("node-count")).toContainText("13 nodes");
    await expect(page.getByTestId("panel-label")).toHaveText("archive-agent");

    // Shortcut: I toggles the incident view of the selected node (the archive agent has no
    // dependents, so the panel says so).
    await page.getByTestId("impact-clear").click();
    await expect(page.getByTestId("impact-panel")).toHaveCount(0);
    await page.keyboard.press("i");
    await expect(page.getByTestId("impact-panel")).toBeVisible();
    await expect(page.getByText("Nothing depends on this node within 2 levels.")).toBeVisible();
    await page.keyboard.press("i");
    await expect(page.getByTestId("impact-panel")).toHaveCount(0);
  });

  test("a dependent that turns failing updates the list without any click", async ({
    page,
    request,
  }) => {
    const domain = incidentDomain("flip-dependent");
    await openLiveMap(page, mapUrl(domain));
    await showImpactFor(page, "ledger", "ledger-service");
    const billingRow = page
      .getByTestId("impact-depth-1")
      .getByTestId("impact-row")
      .filter({ hasText: "billing-agent" });
    await expect(billingRow).toHaveText("billing-agent, Agent, health Healthy");

    await control(request, domain, { action: "flip", node_id: I.billing, health: "failing" });
    await sendHealthDelta(page, [
      { id: I.billing, kind: "agent", label: "billing-agent", health: "failing" },
    ]);

    // Recomputed after the quiet period; the row now says Failing in words.
    await expect(billingRow).toHaveText("billing-agent, Agent, health Failing", {
      timeout: RECOMPUTE_TIMEOUT,
    });
    await expect(page.getByTestId("impact-status")).toHaveText(
      "5 dependents affected by ledger-service",
    );
    // Not the other dependent.
    await expect(page.getByTestId("impact-row").filter({ hasText: "refund-agent" })).toHaveText(
      "refund-agent, Agent, health Healthy",
    );
  });

  test("a selected node that turns failing starts its impact view by itself", async ({
    page,
    request,
  }) => {
    const domain = incidentDomain("auto-start");
    await openLiveMap(page, mapUrl(domain));
    await searchAndSelect(page, "billing", "billing-agent");
    await expect(page.getByTestId("panel-label")).toHaveText("billing-agent");
    await expect(page.getByTestId("impact-panel")).toHaveCount(0);

    await control(request, domain, { action: "flip", node_id: I.billing, health: "failing" });
    await sendHealthDelta(page, [
      { id: I.billing, kind: "agent", label: "billing-agent", health: "failing" },
    ]);

    await expect(page.getByTestId("impact-panel")).toBeVisible();
    await expect(page.getByTestId("impact-status")).toHaveText(
      "1 dependent affected by billing-agent",
    );
    await expect(page.getByTestId("impact-row")).toHaveText([
      "reconcile-sub-agent, Sub-agent, health Healthy",
    ]);
    await expect(page.getByTestId("metric-health")).toContainText("Failing");
    // The map did not move under the user: no banner for the node they are looking at.
    await expect(page.getByTestId("impact-banner")).toHaveCount(0);
  });

  test("another node turning failing offers a banner instead of moving the map", async ({
    page,
    request,
  }) => {
    const domain = incidentDomain("banner");
    await openLiveMap(page, mapUrl(domain));
    await showImpactFor(page, "ledger", "ledger-service");
    await expect(page.getByTestId("impact-status")).toContainText("5 dependents");

    await control(request, domain, { action: "flip", node_id: I.tax, health: "failing" });
    await sendHealthDelta(page, [
      { id: I.tax, kind: "tool", label: "tax-tool", health: "failing" },
    ]);

    const banner = page.getByTestId("impact-banner");
    await expect(banner).toContainText("tax-tool just turned failing.");
    // The incident view is still the ledger's.
    await expect(page.getByTestId("impact-status")).toContainText("affected by ledger-service");
    await banner.getByRole("button", { name: "Show impact" }).click();
    await expect(banner).toHaveCount(0);
    // billing-agent and reconcile-sub-agent depend on the tax tool.
    await expect(page.getByTestId("impact-status")).toHaveText("2 dependents affected by tax-tool");
    await expect(page.getByTestId("impact-row")).toHaveText([
      "billing-agent, Agent, health Healthy",
      "reconcile-sub-agent, Sub-agent, health Healthy",
    ]);
  });

  test("a banner can be dismissed", async ({ page, request }) => {
    const domain = incidentDomain("dismiss");
    await openLiveMap(page, mapUrl(domain));
    await control(request, domain, { action: "flip", node_id: I.queue, health: "failing" });
    await sendHealthDelta(page, [
      { id: I.queue, kind: "service", label: "queue-service", health: "failing" },
    ]);
    const banner = page.getByTestId("impact-banner");
    await expect(banner).toContainText("queue-service just turned failing.");
    await banner.getByRole("button", { name: "Dismiss" }).click();
    await expect(banner).toHaveCount(0);
    await expect(page.getByTestId("impact-panel")).toHaveCount(0);
  });
});
