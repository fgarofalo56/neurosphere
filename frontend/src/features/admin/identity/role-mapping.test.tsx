import { cleanup, screen, within } from "@testing-library/react";
import { afterEach, beforeAll, describe, expect, it } from "vitest";
import { axe } from "vitest-axe";
import { fakeFetch, problem, renderAdmin, stubResizeObserver } from "../shared/test-support";
import { ME_ACCESS_PATH, ROLE_MAPPING_PATH } from "./hooks";
import { MY_ACCESS_ID, MyAccessPanel } from "./MyAccessPanel";
import { RoleMappingPanel } from "./RoleMappingPanel";
import { IDENTITY_STRINGS } from "./strings";
import type { MyAccessView, RoleMappingView } from "./types";

beforeAll(stubResizeObserver);
afterEach(cleanup);

const TENANT = "11111111-1111-1111-1111-111111111111";
const AUDIENCE = "22222222-2222-2222-2222-222222222222";
const DENIED = "this operation needs `policy.manage`";

const MAPPING: RoleMappingView = {
  active: true,
  tenant_id: TENANT,
  audience: AUDIENCE,
  cloud: "commercial",
  entries: [
    {
      id: "ns-admins",
      claim: "roles",
      value: "admin",
      role: "admin",
      domain_mode: "all",
      domain_ids: [],
      customer_control: true,
    },
    {
      id: "finance-analysts",
      claim: "groups",
      value: "33333333-3333-3333-3333-333333333333",
      role: "analyst",
      domain_mode: "explicit",
      domain_ids: ["commercial:e2e:catalog:domain:finance", "commercial:e2e:catalog:domain:hr"],
      customer_control: false,
    },
  ],
};

const NO_MAPPING: RoleMappingView = {
  active: false,
  tenant_id: null,
  audience: null,
  cloud: "commercial",
  entries: [],
};

const ACCESS: MyAccessView = {
  mapping_configured: true,
  groups_overage: false,
  roles: [
    {
      role: "admin",
      source: "entra_app_role",
      mapping_entry_id: "ns-admins",
      domain_count: 4,
      customer_control: true,
      expires_at: "2026-11-18T15:00:00Z",
    },
    {
      role: "analyst",
      source: "entra_group",
      mapping_entry_id: "finance-analysts",
      domain_count: 2,
      customer_control: false,
      expires_at: "2026-11-18T15:00:00Z",
    },
    {
      role: "viewer",
      source: "policy_store",
      mapping_entry_id: null,
      domain_count: 1,
      customer_control: false,
      expires_at: null,
    },
  ],
};

const never = (() => new Promise<Response>(() => undefined)) as typeof fetch;

function noEditableControl(root: HTMLElement): void {
  const box = within(root);
  for (const role of ["textbox", "combobox", "checkbox", "radio", "switch", "spinbutton"]) {
    expect(box.queryAllByRole(role, { hidden: true })).toHaveLength(0);
  }
  expect(root.querySelectorAll("input, select, textarea, form")).toHaveLength(0);
  expect(box.queryAllByRole("button", { hidden: true })).toHaveLength(0);
}

const violations = async (container: HTMLElement): Promise<string[]> =>
  (await axe(container)).violations.map((v) => `${v.id}: ${v.help}`);

describe("RoleMappingPanel", () => {
  it("shows the binding, each entry and both notes, with no editable control", async () => {
    const { impl, calls } = fakeFetch((req) =>
      req.url.pathname === ROLE_MAPPING_PATH ? { body: MAPPING } : undefined,
    );
    const { container } = renderAdmin(<RoleMappingPanel />, impl);
    const rows = await screen.findAllByTestId("role-mapping-row");
    expect(rows).toHaveLength(2);
    expect(rows[0]?.textContent).toContain("ns-admins");
    expect(rows[0]?.textContent).toContain("App role (roles claim)");
    expect(rows[0]?.textContent).toContain("All registered domains");
    expect(rows[0]?.textContent).toContain("Yes");
    expect(rows[1]?.textContent).toContain("Group (groups claim)");
    expect(rows[1]?.textContent).toContain("2 listed domains");
    expect(rows[1]?.textContent).toContain("No");
    const binding = screen.getByTestId("role-mapping-binding");
    expect(binding.textContent).toContain(TENANT);
    expect(binding.textContent).toContain(AUDIENCE);
    expect(binding.textContent).toContain("commercial");
    expect(screen.getByTestId("role-mapping-active").textContent).toBe("Active");
    expect(screen.getByTestId("role-mapping-assignment-note").textContent).toContain(
      "Cloud Application Administrator",
    );
    expect(screen.getByTestId("role-mapping-principals-note").textContent).toContain(
      "not in the principals list",
    );
    noEditableControl(screen.getByTestId("role-mapping-panel"));
    expect(calls.every((c) => c.method === "GET")).toBe(true);
    expect(await violations(container)).toEqual([]);
  });

  it("shows loading, then the empty state when no mapping is configured", async () => {
    renderAdmin(<RoleMappingPanel />, never);
    expect(screen.getByTestId("role-mapping-loading")).toBeTruthy();
    cleanup();
    const { impl } = fakeFetch(() => ({ body: NO_MAPPING }));
    renderAdmin(<RoleMappingPanel />, impl);
    expect((await screen.findByTestId("role-mapping-empty")).textContent).toContain(
      IDENTITY_STRINGS.mapping.empty,
    );
    expect(screen.queryByTestId("role-mapping-row")).toBeNull();
    noEditableControl(screen.getByTestId("role-mapping-panel"));
  });

  it("shows the forbidden state naming the permission, and an error state on failure", async () => {
    const denied = fakeFetch(() => problem(403, "forbidden", DENIED));
    renderAdmin(<RoleMappingPanel />, denied.impl);
    await screen.findByTestId("role-mapping-forbidden-state");
    expect(screen.getByTestId("role-mapping-forbidden-detail").textContent).toContain(
      "policy.manage",
    );
    expect(screen.getByTestId("role-mapping-forbidden-access-link").getAttribute("href")).toBe(
      `#${MY_ACCESS_ID}`,
    );
    expect(screen.queryByTestId("role-mapping-row")).toBeNull();
    cleanup();
    const down = fakeFetch(() => problem(503, "dependency_transient", "down"));
    renderAdmin(<RoleMappingPanel />, down.impl);
    await screen.findByTestId("role-mapping-unavailable-state");
    expect(screen.queryByTestId("role-mapping-empty")).toBeNull();
  });
});

describe("MyAccessPanel", () => {
  it("lists roles with source badges, entry ids, the whole-deployment marker and expiry", async () => {
    const { impl, calls } = fakeFetch((req) =>
      req.url.pathname === ME_ACCESS_PATH ? { body: ACCESS } : undefined,
    );
    const { container } = renderAdmin(<MyAccessPanel />, impl);
    const rows = await screen.findAllByTestId("my-access-row");
    expect(rows).toHaveLength(3);
    expect(screen.getAllByTestId("my-access-source").map((b) => b.textContent)).toEqual([
      "Entra app role",
      "Entra group",
      "Policy store",
    ]);
    expect(rows[0]?.textContent).toContain("ns-admins");
    expect(rows[0]?.textContent).toContain("4");
    expect(within(rows[0] as HTMLElement).getByTestId("my-access-whole").textContent).toBe(
      "Whole deployment",
    );
    expect(within(rows[1] as HTMLElement).queryByTestId("my-access-whole")).toBeNull();
    expect(rows[1]?.textContent).toContain("finance-analysts");
    expect(rows[0]?.querySelector("time")?.getAttribute("datetime")).toContain("2026-11-18");
    expect(rows[2]?.textContent).toContain("No expiry");
    expect(screen.queryByTestId("my-access-overage")).toBeNull();
    expect(container.querySelector(`#${MY_ACCESS_ID}`)).not.toBeNull();
    noEditableControl(screen.getByTestId("my-access-panel"));
    expect(calls.map((c) => c.method)).toEqual(["GET"]);
    expect(await violations(container)).toEqual([]);
  });

  it("shows the overage notice when group roles were not applied", async () => {
    const { impl } = fakeFetch(() => ({ body: { ...ACCESS, groups_overage: true } }));
    renderAdmin(<MyAccessPanel />, impl);
    expect((await screen.findByTestId("my-access-overage")).textContent).toContain(
      "Group-based roles were not applied",
    );
  });

  it("shows loading, empty and error states", async () => {
    renderAdmin(<MyAccessPanel />, never);
    expect(screen.getByTestId("my-access-loading")).toBeTruthy();
    cleanup();
    const empty = fakeFetch(() => ({
      body: { mapping_configured: false, groups_overage: false, roles: [] },
    }));
    renderAdmin(<MyAccessPanel />, empty.impl);
    expect((await screen.findByTestId("my-access-empty")).textContent).toContain(
      IDENTITY_STRINGS.myAccess.empty,
    );
    expect(screen.getByTestId("my-access-mapping").textContent).toBe(
      IDENTITY_STRINGS.myAccess.mappingNotConfigured,
    );
    cleanup();
    const down = fakeFetch(() => problem(503, "dependency_transient", "down"));
    renderAdmin(<MyAccessPanel />, down.impl);
    await screen.findByTestId("my-access-unavailable-state");
    expect(screen.queryByTestId("my-access-empty")).toBeNull();
  });
});
