import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Route, Routes } from "react-router";
import { afterEach, beforeAll, describe, expect, it } from "vitest";
import { axe } from "vitest-axe";
import { identityPaths } from "../shared/adminPaths";
import {
  fakeFetch,
  problem,
  renderAdmin,
  stubResizeObserver,
  type FakeHandler,
  type FakeReply,
} from "../shared/test-support";
import { buildRequest, EMPTY_FORM, diffOf, formValid, isExpired, toTimestamp } from "./changes";
import { PrincipalDetailPage } from "./PrincipalDetailPage";
import { ME_ACCESS_PATH, ROLE_MAPPING_PATH } from "./hooks";
import { PrincipalsPage } from "./PrincipalsPage";
import type { MyAccessView, PrincipalSummary, RoleMappingView } from "./types";

beforeAll(stubResizeObserver);
afterEach(cleanup);

const PID = "commercial:e2e:entra:person:p-" + "a".repeat(64);
const PID2 = "commercial:e2e:entra:person:p-" + "b".repeat(64);
const DOMAIN = "commercial:e2e:catalog:domain:finance";
const ETAG = '"p1"';

function summary(over: Partial<PrincipalSummary> = {}): PrincipalSummary {
  return {
    principal: { principal_id: PID, principal_kind: "user" },
    policy_version: "pv-1",
    memberships: [DOMAIN],
    assignments: [
      {
        assignment_id: "role-1",
        role: "analyst",
        domain_ids: [DOMAIN],
        expires_at: "2020-01-01T00:00:00Z",
        reason: "trial",
      },
    ],
    grants: [
      {
        grant_id: "grant-1",
        resource_id: "commercial:e2e:catalog:report:q",
        permissions: ["read"],
        expires_at: "2099-01-01T00:00:00Z",
        reason: "audit_support",
      },
    ],
    revocation: {
      principal_id: PID,
      revoked: false,
      mode: null,
      revoked_at: null,
      reason: null,
      revoked_by: null,
      propagation_bound_seconds: 30,
    },
    ...over,
  };
}

const REVOKED = summary({
  revocation: {
    principal_id: PID,
    revoked: true,
    mode: "until_lifted",
    revoked_at: "2026-10-01T09:00:00Z",
    reason: "offboarding",
    revoked_by: PID,
    propagation_bound_seconds: 30,
  },
});

function detailRoutes(handler: FakeHandler) {
  return fakeFetch((req) => {
    const out = handler(req);
    if (out !== undefined) return out;
    if (req.method === "GET" && req.url.pathname === identityPaths.principal(PID)) {
      return { body: summary(), headers: { ETag: ETAG } };
    }
    return undefined;
  });
}

function renderDetail(handler: FakeHandler) {
  const fake = detailRoutes(handler);
  renderAdmin(
    <Routes>
      <Route path="/admin/identity/principal" element={<PrincipalDetailPage />} />
    </Routes>,
    fake.impl,
    `/admin/identity/principal?principal_id=${encodeURIComponent(PID)}`,
  );
  return fake;
}

function dialog() {
  return within(screen.getByTestId("change-confirm-dialog"));
}

async function fill(label: string | RegExp, value: string): Promise<void> {
  const input = dialog().getByLabelText(label);
  await userEvent.clear(input);
  await userEvent.type(input, value);
}

function submitButton(): HTMLElement {
  return dialog().getByRole("button", { name: "Confirm change", hidden: true });
}

const OWN_ACCESS: MyAccessView = {
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
  ],
};

const ROLE_MAPPING: RoleMappingView = {
  active: true,
  tenant_id: "11111111-1111-1111-1111-111111111111",
  audience: "22222222-2222-2222-2222-222222222222",
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
  ],
};

/** The PRP-138 panels on the Identity page read their own routes; the list handler gets the rest. */
function withPanels(handler: FakeHandler): FakeHandler {
  return (req) => {
    if (req.url.pathname === ME_ACCESS_PATH) return { body: OWN_ACCESS };
    if (req.url.pathname === ROLE_MAPPING_PATH) return { body: ROLE_MAPPING };
    return handler(req);
  };
}

describe("PrincipalsPage", () => {
  const page = (items: PrincipalSummary[], next: string | null = null): FakeReply => ({
    body: { items, next_cursor: next, truncated: false },
  });

  it("lists principals by id with a revoked state and no names", async () => {
    const other = { ...REVOKED, principal: { principal_id: PID2, principal_kind: "user" } };
    const { impl } = fakeFetch(withPanels(() => page([summary(), other])));
    renderAdmin(<PrincipalsPage />, impl);
    expect(await screen.findAllByTestId("principal-row")).toHaveLength(2);
    expect(screen.getAllByText(PID).length).toBeGreaterThan(0);
    expect(screen.getByText("Revoked")).toBeTruthy();
    expect(screen.getByRole("link", { name: PID, hidden: true }).getAttribute("href")).toContain(
      "/admin/identity/principal?principal_id=",
    );
  });

  it("pages with the server cursor", async () => {
    const { impl, calls } = fakeFetch(
      withPanels((req) =>
        req.url.searchParams.get("cursor") === "next-1"
          ? page([REVOKED])
          : page([summary()], "next-1"),
      ),
    );
    renderAdmin(<PrincipalsPage />, impl);
    await userEvent.click(await screen.findByRole("button", { name: "Next page" }));
    await waitFor(() => expect(screen.getAllByTestId("principal-row")).toHaveLength(1));
    const lastList = calls.filter((c) => c.url.pathname === identityPaths.principals()).at(-1);
    expect(lastList?.url.searchParams.get("cursor")).toBe("next-1");
    expect(lastList?.url.searchParams.get("limit")).toBe("25");
  });

  it("shows empty, forbidden and error states, never an empty list for a failure", async () => {
    const empty = fakeFetch(withPanels(() => page([])));
    renderAdmin(<PrincipalsPage />, empty.impl);
    await screen.findByTestId("empty-state");
    cleanup();
    const denied = fakeFetch(
      withPanels(() => problem(403, "forbidden", "deployment_scope_required")),
    );
    renderAdmin(<PrincipalsPage />, denied.impl);
    await screen.findByTestId("forbidden-state");
    cleanup();
    const down = fakeFetch(withPanels(() => problem(503, "dependency_transient", "down")));
    renderAdmin(<PrincipalsPage />, down.impl);
    await screen.findByTestId("unavailable-state");
    expect(screen.queryByTestId("empty-state")).toBeNull();
  });

  it("shows a loading state first", () => {
    renderAdmin(<PrincipalsPage />, (() => new Promise<Response>(() => undefined)) as typeof fetch);
    expect(screen.getByTestId("loading-state")).toBeTruthy();
  });

  it("renders the role mapping and own-access panels after the list, read only", async () => {
    const { impl, calls } = fakeFetch(withPanels(() => page([summary()])));
    const { container } = renderAdmin(<PrincipalsPage />, impl);
    await screen.findAllByTestId("principal-row");
    await screen.findAllByTestId("role-mapping-row");
    await screen.findAllByTestId("my-access-row");
    const list = screen.getAllByTestId("principal-row")[0] as HTMLElement;
    const mappingPanel = screen.getByTestId("role-mapping-panel");
    const accessPanel = screen.getByTestId("my-access-panel");
    const follows = (a: Node, b: Node): boolean =>
      (a.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING) !== 0;
    expect(follows(list, mappingPanel)).toBe(true);
    expect(follows(mappingPanel, accessPanel)).toBe(true);
    expect(screen.getByTestId("my-access-source").textContent).toBe("Entra app role");
    for (const panel of [mappingPanel, accessPanel]) {
      expect(panel.querySelectorAll("input, select, textarea, form, button")).toHaveLength(0);
    }
    expect(calls.every((c) => c.method === "GET")).toBe(true);
    const violations = (await axe(container)).violations.map((v) => `${v.id}: ${v.help}`);
    expect(violations).toEqual([]);
  });

  it("links a denied list to the own-access panel, which still loads", async () => {
    const { container } = renderAdmin(
      <PrincipalsPage />,
      fakeFetch((req) => {
        if (req.url.pathname === ME_ACCESS_PATH) return { body: { ...OWN_ACCESS, roles: [] } };
        return problem(403, "forbidden", "this operation needs `policy.manage`");
      }).impl,
    );
    await screen.findByTestId("forbidden-state");
    expect(screen.getByTestId("forbidden-detail").textContent).toContain("policy.manage");
    expect(screen.getByTestId("forbidden-access-link").getAttribute("href")).toBe("#my-access");
    await screen.findByTestId("role-mapping-forbidden-state");
    await screen.findByTestId("my-access-empty");
    expect(container.querySelector("#my-access")).not.toBeNull();
    const violations = (await axe(container)).violations.map((v) => `${v.id}: ${v.help}`);
    expect(violations).toEqual([]);
  });
});

describe("PrincipalDetailPage", () => {
  it("shows memberships, assignments with an expired label, grants and the ETag", async () => {
    renderDetail(() => undefined);
    await screen.findByTestId("principal-etag");
    expect(screen.getByTestId("principal-etag").textContent).toBe(ETAG);
    expect(screen.getAllByTestId("membership-row")).toHaveLength(1);
    expect(screen.getByTestId("assignment-row").textContent).toContain("Expired");
    expect(screen.getAllByTestId("grant-row")).toHaveLength(1);
    expect(screen.queryByTestId("revoked-banner")).toBeNull();
  });

  it("assigns a role through the confirm dialog with If-Match and a reason code", async () => {
    const { calls } = renderDetail((req) =>
      req.method === "PUT"
        ? { body: summary({ memberships: [] }), headers: { ETag: '"p2"' } }
        : undefined,
    );
    await userEvent.click(await screen.findByRole("button", { name: "Assign role" }));
    expect(dialog().getByTestId("change-target").textContent).toBe(PID);
    expect(dialog().getByTestId("change-version").textContent).toBe(ETAG);
    expect(submitButton().hasAttribute("disabled")).toBe(true);
    await fill(/Domain ids/, DOMAIN);
    await fill(/Reason code/, "Bad Reason");
    expect(submitButton().hasAttribute("disabled")).toBe(true);
    await fill(/Reason code/, "access_review");
    expect(dialog().getByTestId("change-diff").textContent).toContain(`viewer on ${DOMAIN}`);
    await userEvent.click(submitButton());
    await screen.findByTestId("change-done");
    const put = calls.find((c) => c.method === "PUT");
    expect(put?.headers.get("If-Match")).toBe(ETAG);
    expect(put?.url.pathname).toContain("/role-assignments/role-");
    expect(put?.body).toMatchObject({
      op: "assign",
      role: "viewer",
      domain_ids: [DOMAIN],
      reason: "access_review",
      principal_id: PID,
    });
  });

  it("removes a role and a membership with the reason as a query parameter", async () => {
    const { calls } = renderDetail((req) =>
      req.method === "DELETE" ? { body: summary(), headers: { ETag: '"p2"' } } : undefined,
    );
    await userEvent.click(
      (await screen.findAllByRole("button", { name: "Remove" }))[1] as HTMLElement,
    );
    await fill(/Reason code/, "cleanup");
    await userEvent.click(submitButton());
    await screen.findByTestId("change-done");
    const del = calls.find((c) => c.method === "DELETE");
    expect(del?.url.pathname).toBe(identityPaths.role(PID, "role-1"));
    expect(del?.url.searchParams.get("reason")).toBe("cleanup");
    expect(del?.headers.get("If-Match")).toBe(ETAG);
  });

  it("requires an expiry for a grant and sends it as a UTC timestamp", async () => {
    const { calls } = renderDetail((req) =>
      req.method === "PUT" ? { body: summary(), headers: { ETag: '"p2"' } } : undefined,
    );
    await userEvent.click(await screen.findByRole("button", { name: "Put grant" }));
    await fill(/Resource id/, "commercial:e2e:catalog:report:x");
    await fill(/Reason code/, "audit_support");
    expect(submitButton().hasAttribute("disabled")).toBe(true);
    fireEvent.change(dialog().getByLabelText(/Expiry/), { target: { value: "2099-01-01T00:00" } });
    await waitFor(() => expect(submitButton().hasAttribute("disabled")).toBe(false));
    await userEvent.click(submitButton());
    await screen.findByTestId("change-done");
    const put = calls.find((c) => c.method === "PUT");
    expect((put?.body as { expires_at: string }).expires_at).toBe(toTimestamp("2099-01-01T00:00"));
    expect((put?.body as { permissions: string[] }).permissions).toEqual(["read"]);
  });

  it("removes a grant without a reason code", async () => {
    const { calls } = renderDetail((req) =>
      req.method === "DELETE" ? { body: summary(), headers: { ETag: '"p2"' } } : undefined,
    );
    await userEvent.click(
      (await screen.findAllByRole("button", { name: "Remove" }))[2] as HTMLElement,
    );
    expect(dialog().getByTestId("change-reason-note")).toBeTruthy();
    await userEvent.click(submitButton());
    await screen.findByTestId("change-done");
    expect(calls.find((c) => c.method === "DELETE")?.url.pathname).toBe(
      identityPaths.grant(PID, "grant-1"),
    );
  });

  it("shows reload guidance on a 409 and the API text on a 422", async () => {
    let n = 0;
    renderDetail((req) => {
      if (req.method !== "DELETE") return undefined;
      n += 1;
      return n === 1
        ? problem(409, "stale_version", "etag_mismatch")
        : problem(422, "invalid_schema", "reason is not accepted for this change");
    });
    await userEvent.click(
      (await screen.findAllByRole("button", { name: "Remove" }))[0] as HTMLElement,
    );
    await fill(/Reason code/, "cleanup");
    await userEvent.click(submitButton());
    expect((await screen.findByTestId("change-error")).textContent).toContain(
      "changed since you loaded",
    );
    await userEvent.click(submitButton());
    await waitFor(() =>
      expect(screen.getByTestId("change-error").textContent).toContain(
        "reason is not accepted for this change",
      ),
    );
    expect(screen.queryByTestId("change-done")).toBeNull();
  });

  it("revokes with a mode and reason, and lifts from the persistent banner", async () => {
    const revoke = renderDetail((req) =>
      req.method === "POST" ? { body: REVOKED.revocation } : undefined,
    );
    await userEvent.click(await screen.findByRole("button", { name: "Revoke principal" }));
    await fill(/Reason code/, "offboarding");
    await userEvent.click(dialog().getByLabelText(/Issued before now/));
    await userEvent.click(submitButton());
    await screen.findByTestId("change-done");
    const post = revoke.calls.find((c) => c.method === "POST");
    expect(post?.url.pathname).toBe(identityPaths.revocation(PID));
    expect(post?.body).toMatchObject({ mode: "issued_before", reason: "offboarding" });
    expect(post?.headers.get("If-Match")).toBeNull();
    cleanup();

    const lift = fakeFetch((req) => {
      if (req.method === "DELETE") return { body: summary().revocation };
      return { body: REVOKED, headers: { ETag: ETAG } };
    });
    renderAdmin(
      <Routes>
        <Route path="/admin/identity/principal" element={<PrincipalDetailPage />} />
      </Routes>,
      lift.impl,
      `/admin/identity/principal?principal_id=${encodeURIComponent(PID)}`,
    );
    await screen.findByTestId("revoked-banner");
    await userEvent.click(screen.getByRole("button", { name: "Lift revocation" }));
    await fill(/Reason code/, "mistake");
    await userEvent.click(submitButton());
    await screen.findByTestId("change-done");
    const del = lift.calls.find((c) => c.method === "DELETE");
    expect(del?.url.pathname).toBe(identityPaths.revocation(PID));
    expect(del?.url.searchParams.get("reason")).toBe("mistake");
  });

  it("renders a forbidden state when the API answers 403", async () => {
    const { impl } = fakeFetch(() => problem(403, "forbidden", "target_out_of_scope"));
    renderAdmin(
      <Routes>
        <Route path="/admin/identity/principal" element={<PrincipalDetailPage />} />
      </Routes>,
      impl,
      `/admin/identity/principal?principal_id=${encodeURIComponent(PID)}`,
    );
    await screen.findByTestId("forbidden-state");
    expect(screen.queryByRole("button", { name: "Assign role" })).toBeNull();
  });

  it("asks for a principal when the query parameter is missing", () => {
    const { impl } = fakeFetch(() => undefined);
    renderAdmin(
      <Routes>
        <Route path="/admin/identity/principal" element={<PrincipalDetailPage />} />
      </Routes>,
      impl,
      "/admin/identity/principal",
    );
    expect(screen.getByTestId("empty-state")).toBeTruthy();
  });
});

describe("change helpers", () => {
  it("validates, diffs and builds each request", () => {
    const form = { ...EMPTY_FORM, reason: "ok_reason", domainIds: `${DOMAIN}, `, domainId: DOMAIN };
    expect(formValid({ kind: "assign-role" }, form)).toBe(true);
    expect(formValid({ kind: "assign-role" }, { ...form, domainIds: "" })).toBe(false);
    expect(formValid({ kind: "add-membership" }, { ...form, reason: "Bad" })).toBe(false);
    expect(formValid({ kind: "remove-grant" }, EMPTY_FORM)).toBe(true);
    const membership = buildRequest({ kind: "add-membership" }, form, {
      principalId: PID,
      etag: undefined,
      expiry: null,
    });
    expect(membership.ifMatch).toBeUndefined();
    expect(membership.path).toBe(identityPaths.membership(PID, DOMAIN));
    expect(diffOf({ kind: "remove-membership", domainId: DOMAIN }, form, summary())[0]?.after).toBe(
      "removed",
    );
    expect(diffOf({ kind: "lift" }, form, REVOKED)[0]?.before).toBe("until_lifted");
  });

  it("treats a past expiry as expired and no expiry as never", () => {
    expect(isExpired("2020-01-01T00:00:00Z")).toBe(true);
    expect(isExpired("2099-01-01T00:00:00Z")).toBe(false);
    expect(isExpired(null)).toBe(false);
  });
});
