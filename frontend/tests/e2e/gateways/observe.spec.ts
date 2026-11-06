import AxeBuilder from "@axe-core/playwright";
import type { Page } from "@playwright/test";
import { expect, test } from "../../e2e-support/fixtures.ts";
import { WCAG_TAGS } from "../../helpers/axe.ts";
import { DOMAIN_OK, GATEWAY_BUSY, GATEWAY_OBSERVE } from "../../mock-api/server.ts";

// PRP-33 item 7: the gateway list (tier, diagnostics, last sync), the read-only inventory detail
// and the catalog Grant and McpServer renderers, against the mock API. Visual baselines are
// Docker-only and are captured by the visual project, not by this spec.

const D = encodeURIComponent(DOMAIN_OK);
const GRANT = "commercial:e2e:catalog:grant:finance-mcp-access";
const MCP = "commercial:e2e:catalog:mcp_server:finance-tools";

async function axeViolations(page: Page) {
  const results = await new AxeBuilder({ page })
    .withTags([...WCAG_TAGS])
    .exclude("[data-tabster-dummy]")
    .analyze();
  return results.violations.map((v) => ({ id: v.id, impact: v.impact, nodes: v.nodes.length }));
}

test("the list shows tier, diagnostics state and last sync, and links to the detail", async ({
  page,
}) => {
  await page.goto(`/gateways?domain_id=${D}`);
  const panel = page
    .getByTestId("gateway-panel")
    .filter({ has: page.getByRole("heading", { name: "apim-observe" }) });
  await expect(panel.getByTestId("gateway-tier")).toHaveText("standard_v2");
  const diagnostics = panel.getByTestId("gateway-diagnostics");
  await expect(diagnostics).toContainText("GatewayLogs: enabled");
  await expect(diagnostics).toContainText("GatewayMCPLogs: not enabled");
  await expect(panel.getByTestId("gateway-last-sync")).toContainText("Synced");
  await expect(panel.getByTestId("gateway-freshness")).toHaveText("5 min");
  await expect(panel.getByTestId("gateway-coverage")).toHaveText("85%");

  const busy = page
    .getByTestId("gateway-panel")
    .filter({ has: page.getByRole("heading", { name: "apim-busy" }) });
  await expect(busy.getByTestId("gateway-last-sync")).toContainText("Never synced");
  await expect(busy.getByTestId("gateway-coverage")).toHaveText("Not reported");

  await panel.getByTestId("gateway-detail-link").click();
  await expect(page.getByTestId("inventory-apis")).toBeVisible();
  expect(page.url()).toContain(`gateway_id=${GATEWAY_OBSERVE}`);
});

test("the detail lists the inventory tables with pool members and circuit breakers", async ({
  page,
}) => {
  await page.goto(`/gateways/detail?domain_id=${D}&gateway_id=${GATEWAY_OBSERVE}`);
  await expect(page.getByTestId("inventory-apis-row")).toHaveCount(2);
  await expect(page.getByTestId("inventory-products-row")).toHaveCount(1);
  await expect(page.getByTestId("inventory-backends-row")).toHaveCount(2);
  await expect(page.getByTestId("pool-member")).toHaveCount(2);
  await expect(page.getByTestId("circuit-breaker")).toContainText("trip-on-429");
  await expect(page.getByTestId("inventory-fragments-row")).toContainText("llm-token-limit");
  await expect(page.getByTestId("inventory-subscriptions-row")).toContainText(
    "sub-finance-analyst",
  );
  expect(await axeViolations(page)).toEqual([]);
});

test("a gateway that never synced shows an empty inventory, not an error", async ({ page }) => {
  await page.goto(`/gateways/detail?domain_id=${D}&gateway_id=${GATEWAY_BUSY}`);
  await expect(page.getByTestId("inventory-empty")).toBeVisible();
  await expect(page.getByTestId("query-error")).toHaveCount(0);
});

test("the list page has no axe violations", async ({ page }) => {
  await page.goto(`/gateways?domain_id=${D}`);
  await expect(page.getByTestId("gateway-diagnostics").first()).toBeVisible();
  expect(await axeViolations(page)).toEqual([]);
});

test("the catalog renders a Grant with its target and the grants_access_to relation", async ({
  page,
}) => {
  await page.goto(`/catalog/entity?domain_id=${D}&entity_id=${encodeURIComponent(GRANT)}`);
  await expect(page.getByTestId("grant-principal")).toContainText("Finance analysts");
  await expect(page.getByTestId("grant-target")).toContainText(MCP);
  await expect(page.getByTestId("grant-limits")).toContainText("60 MCP calls/min");
  await expect(page.getByTestId("neighbor-row")).toContainText("grants access to");
  expect(await axeViolations(page)).toEqual([]);
});

test("the catalog renders an McpServer with transport, auth kind and tools", async ({ page }) => {
  await page.goto(`/catalog/entity?domain_id=${D}&entity_id=${encodeURIComponent(MCP)}`);
  await expect(page.getByTestId("mcp-transport")).toHaveText("streamable_http");
  await expect(page.getByTestId("mcp-auth")).toHaveText("entra");
  await expect(page.getByTestId("mcp-tool")).toHaveCount(2);
  await expect(page.getByTestId("neighbor-row")).toContainText("grants access to");
  expect(await axeViolations(page)).toEqual([]);
});
