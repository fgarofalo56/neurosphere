import { cleanup, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { afterEach, describe, expect, it } from "vitest";
import { EntityTypeRows, relationLabel } from "./EntityTypeDetails";
import type { CatalogEntityView } from "./explorerTypes";

afterEach(cleanup);

const base: CatalogEntityView = {
  id: "x",
  entity_type: "grant",
  domain_id: "d",
  version: 1,
  etag: "e",
  lifecycle_status: "active",
  updated_at: "2026-10-20T10:00:00Z",
};

function show(entity: CatalogEntityView): void {
  render(
    <MemoryRouter>
      <dl>
        <EntityTypeRows entity={entity} />
      </dl>
    </MemoryRouter>,
  );
}

describe("entity type renderers", () => {
  it("labels grants_access_to and keeps other relations raw", () => {
    expect(relationLabel("grants_access_to")).toBe("grants access to");
    expect(relationLabel("uses_model")).toBe("uses_model");
  });

  it("renders a Grant with a linked MCP server target and its limits", () => {
    show({
      ...base,
      enabled: true,
      principal: { kind: "user", object_id: "o", display: "Ana" },
      target: { kind: "mcp_server", ref: "commercial:e2e:catalog:mcp_server:t" },
      limits: { mcp_calls_per_minute: 60 },
    });
    expect(screen.getByTestId("grant-principal")).toHaveTextContent("Ana (user)");
    expect(screen.getByRole("link", { name: "commercial:e2e:catalog:mcp_server:t" })).toBeTruthy();
    expect(screen.getByTestId("grant-limits")).toHaveTextContent("60 MCP calls/min");
  });

  it("renders an McpServer with auth kind only and flags destructive tools", () => {
    show({
      ...base,
      entity_type: "mcp_server",
      url: "https://t.example.com/mcp",
      transport: "sse",
      auth: { kind: "managed_identity" },
      tools: [{ name: "drop", annotations: { destructive_hint: true } }],
    });
    expect(screen.getByTestId("mcp-auth")).toHaveTextContent("managed_identity");
    expect(screen.getByTestId("mcp-tool")).toHaveTextContent("drop (destructive)");
  });

  it("renders nothing for other types", () => {
    show({ ...base, entity_type: "agent" });
    expect(screen.queryByTestId("grant-principal")).toBeNull();
  });
});
