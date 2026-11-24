import type { Page } from "@playwright/test";
import { expect, test } from "../../e2e-support/fixtures.ts";
import {
  INCIDENT_IDS as I,
  control,
  incidentDomain,
  mapUrl,
  openLiveMap,
  searchAndSelect,
  sendTopology,
} from "./support.ts";

// PRP-77 item 6, story: a new agent or edge appears without a reload when the server pushes a
// `topology` notice with `refetch: true`. The viewport is refetched once per burst, the camera,
// the selection and the position of nodes already on screen are untouched. The notice is sent by
// the fake gateway; the new node is added through the mock control route.

const NEW_NODE = "inc:agent:onboarding";

interface MapProbe {
  camera: { x: number; y: number; ratio: number };
  ledger: { x: number; y: number } | null;
}

function probe(page: Page): Promise<MapProbe> {
  return page.evaluate((ledgerId) => {
    const el = document.querySelector('[data-testid="map-canvas"]') as HTMLElement & {
      __nsMap?: {
        camera: { getState(): { x: number; y: number; ratio: number } };
        sigma: {
          getGraph(): {
            hasNode(id: string): boolean;
            getNodeAttribute(id: string, name: string): number;
          };
        };
      };
    };
    const hook = el.__nsMap;
    if (hook === undefined) throw new Error("map test hook missing");
    const g = hook.sigma.getGraph();
    const { x, y, ratio } = hook.camera.getState();
    return {
      camera: { x, y, ratio },
      ledger: g.hasNode(ledgerId)
        ? { x: g.getNodeAttribute(ledgerId, "x"), y: g.getNodeAttribute(ledgerId, "y") }
        : null,
    };
  }, I.ledger);
}

test.describe("map topology push", () => {
  test("a pushed topology change adds the new node without a reload and keeps selection, camera and positions", async ({
    page,
    request,
  }) => {
    const domain = incidentDomain("push");
    await openLiveMap(page, mapUrl(domain));
    await expect(page.getByTestId("node-count")).toContainText("12 nodes, 10 edges");
    await searchAndSelect(page, "ledger", "ledger-service");
    await expect(page.getByTestId("panel-label")).toHaveText("ledger-service");

    // The jump animates the camera onto the node (300 ms); wait until it stops, then move it
    // somewhere recognisable and record it with the selected node's position.
    let last = "";
    await expect
      .poll(async () => {
        const now = JSON.stringify((await probe(page)).camera);
        const settled = now === last;
        last = now;
        return settled;
      })
      .toBe(true);
    await page.evaluate(() => {
      const el = document.querySelector('[data-testid="map-canvas"]') as HTMLElement & {
        __nsMap?: { camera: { setState(s: { x: number; y: number; ratio: number }): void } };
      };
      el.__nsMap?.camera.setState({ x: 0.31, y: 0.62, ratio: 0.8 });
    });
    const before = await probe(page);
    expect(before.ledger).not.toBeNull();

    let viewportRequests = 0;
    page.on("request", (r) => {
      if (r.url().includes("/viewport")) viewportRequests += 1;
    });
    let reloaded = false;
    page.on("framenavigated", (frame) => {
      if (frame === page.mainFrame()) reloaded = true;
    });

    // The change happens on the server; the notice says refetch is not needed (no effect), then a
    // burst of three notices that say it is.
    await control(request, domain, {
      action: "add_node",
      node_id: NEW_NODE,
      label: "onboarding-agent",
      depends_on: I.ledger,
    });
    await sendTopology(page, false, [NEW_NODE]);
    await sendTopology(page, true, [NEW_NODE]);
    await sendTopology(page, true, [NEW_NODE]);
    await sendTopology(page, true, [NEW_NODE]);

    await expect(page.getByTestId("node-count")).toContainText("13 nodes, 11 edges");
    // One refetch for the whole burst, none for the notice that said refetch was not needed.
    expect(viewportRequests).toBe(1);
    expect(reloaded).toBe(false);

    // Selection kept, panel unchanged, camera and the selected node did not move.
    await expect(page.getByTestId("panel-label")).toHaveText("ledger-service");
    const after = await probe(page);
    expect(after.camera).toEqual(before.camera);
    expect(after.ledger).toEqual(before.ledger);

    // The new node is searchable.
    await page.getByTestId("map-search").fill("onboarding");
    await expect(page.getByTestId("map-search-result")).toHaveCount(1);
  });

  test("the incident view of the selected node is recomputed after a topology change", async ({
    page,
    request,
  }) => {
    const domain = incidentDomain("push-impact");
    await openLiveMap(page, mapUrl(domain));
    await searchAndSelect(page, "ledger", "ledger-service");
    await page.getByTestId("show-impact").click();
    await expect(page.getByTestId("impact-status")).toHaveText(
      "5 dependents affected by ledger-service",
    );

    await control(request, domain, {
      action: "add_node",
      node_id: NEW_NODE,
      label: "onboarding-agent",
      depends_on: I.ledger,
    });
    await sendTopology(page, true, [NEW_NODE]);

    // The new dependent is listed after the viewport refetch and the debounced recompute.
    await expect(page.getByTestId("impact-status")).toHaveText(
      "6 dependents affected by ledger-service",
      { timeout: 15_000 },
    );
    await expect(page.getByTestId("impact-depth-1")).toContainText("onboarding-agent");
    await expect(page.getByTestId("panel-label")).toHaveText("ledger-service");
  });
});
