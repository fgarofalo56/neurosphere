import { cleanup, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeAll, describe, expect, it } from "vitest";
import { platformPaths } from "../shared/adminPaths";
import { fakeFetch, problem, renderAdmin, stubResizeObserver } from "../shared/test-support";
import { DomainsPage } from "./DomainsPage";
import type { DomainView } from "./hooks";

beforeAll(stubResizeObserver);
afterEach(cleanup);

const FIN = "commercial:e2e:catalog:domain:finance";
const CTRL = "commercial:e2e:catalog:domain:control";

function domain(over: Partial<DomainView>): DomainView {
  return {
    domain_id: FIN,
    display_name: "Finance",
    classification: "internal",
    residency_region: "eastus",
    status: "active",
    is_control_domain: false,
    version: 1,
    ...over,
  };
}

const ITEMS = [
  domain({}),
  domain({ domain_id: CTRL, display_name: "Control", is_control_domain: true }),
  domain({
    domain_id: "commercial:e2e:catalog:domain:old",
    display_name: "Old",
    status: "retired",
  }),
];

function dialog() {
  return within(screen.getByTestId("change-confirm-dialog"));
}
function submit(): HTMLElement {
  return dialog().getByRole("button", { name: "Confirm change", hidden: true });
}

describe("DomainsPage", () => {
  it("lists the registry with classification, region, status and a control badge", async () => {
    const { impl, calls } = fakeFetch(() => ({ body: { items: ITEMS } }));
    renderAdmin(<DomainsPage />, impl);
    expect(await screen.findAllByTestId("domain-row")).toHaveLength(3);
    expect(
      screen.getByText("Control domain", { selector: '[data-slot="status-pill"]' }),
    ).toBeTruthy();
    expect(screen.getAllByText("eastus").length).toBe(3);
    expect(calls[0]?.url.searchParams.get("include_retired")).toBe("false");
    await userEvent.click(screen.getByLabelText("Show retired domains"));
    await waitFor(() => expect(calls.at(-1)?.url.searchParams.get("include_retired")).toBe("true"));
  });

  it("disables retiring the control domain with the reason on hover", async () => {
    const { impl } = fakeFetch(() => ({ body: { items: ITEMS } }));
    renderAdmin(<DomainsPage />, impl);
    const button = await screen.findByRole("button", { name: "Retire Control" });
    expect(button.hasAttribute("disabled")).toBe(true);
    expect(button.getAttribute("title")).toContain("control domain cannot be retired");
    expect(screen.getByRole("button", { name: "Retire Old" }).hasAttribute("disabled")).toBe(true);
  });

  it("creates a domain through the confirm dialog", async () => {
    const { impl, calls } = fakeFetch((req) => {
      if (req.method === "POST") return { status: 201, body: ITEMS[0], headers: { ETag: '"d1"' } };
      return { body: { items: ITEMS } };
    });
    renderAdmin(<DomainsPage />, impl);
    await userEvent.click(await screen.findByRole("button", { name: "Create domain" }));
    expect(submit().hasAttribute("disabled")).toBe(true);
    await userEvent.type(dialog().getByLabelText(/Domain id/), "commercial:e2e:catalog:domain:ops");
    await userEvent.type(dialog().getByLabelText(/Display name/), "Ops");
    await userEvent.type(dialog().getByLabelText(/Residency region/), "eastus");
    expect(dialog().getByTestId("change-diff").textContent).toContain("Ops (internal, eastus)");
    await userEvent.click(submit());
    await screen.findByTestId("change-done");
    const post = calls.find((c) => c.method === "POST");
    expect(post?.url.pathname).toBe(platformPaths.domains());
    expect(post?.body).toMatchObject({
      domain_id: "commercial:e2e:catalog:domain:ops",
      display_name: "Ops",
      is_control_domain: false,
      status: "active",
    });
  });

  it("shows the API's 422 text unchanged for a reserved name", async () => {
    const text = "domain name identity-admin is reserved for a customer-level audit chain";
    const { impl } = fakeFetch((req) =>
      req.method === "POST" ? problem(422, "invalid_schema", text) : { body: { items: ITEMS } },
    );
    renderAdmin(<DomainsPage />, impl);
    await userEvent.click(await screen.findByRole("button", { name: "Create domain" }));
    await userEvent.type(dialog().getByLabelText(/Domain id/), "x");
    await userEvent.type(dialog().getByLabelText(/Display name/), "x");
    await userEvent.type(dialog().getByLabelText(/Residency region/), "x");
    await userEvent.click(submit());
    expect((await screen.findByTestId("change-error")).textContent).toContain(text);
  });

  it("reads the current ETag, then retires with If-Match", async () => {
    const { impl, calls } = fakeFetch((req) => {
      if (req.method === "POST") return { body: domain({ status: "retired" }) };
      if (req.url.pathname === platformPaths.domain(FIN)) {
        return { body: domain({}), headers: { ETag: '"d7"' } };
      }
      return { body: { items: ITEMS } };
    });
    renderAdmin(<DomainsPage />, impl);
    await userEvent.click(await screen.findByRole("button", { name: "Retire Finance" }));
    await waitFor(() => expect(dialog().getByTestId("change-version").textContent).toBe('"d7"'));
    expect(dialog().getByTestId("change-target").textContent).toBe(FIN);
    await userEvent.click(submit());
    await screen.findByTestId("change-done");
    const post = calls.find((c) => c.method === "POST");
    expect(post?.url.pathname).toBe(platformPaths.retire(FIN));
    expect(post?.headers.get("If-Match")).toBe('"d7"');
  });

  it("shows reload guidance when the retire is stale", async () => {
    const { impl } = fakeFetch((req) => {
      if (req.method === "POST") return problem(409, "stale_version", "etag_mismatch");
      if (req.url.pathname === platformPaths.domain(FIN)) {
        return { body: domain({}), headers: { ETag: '"d7"' } };
      }
      return { body: { items: ITEMS } };
    });
    renderAdmin(<DomainsPage />, impl);
    await userEvent.click(await screen.findByRole("button", { name: "Retire Finance" }));
    await userEvent.click(
      await within(document.body).findByRole("button", { name: "Confirm change", hidden: true }),
    );
    expect((await screen.findByTestId("change-error")).textContent).toContain(
      "changed since you loaded",
    );
  });

  it("renders empty, forbidden and error states", async () => {
    renderAdmin(<DomainsPage />, fakeFetch(() => ({ body: { items: [] } })).impl);
    await screen.findByTestId("empty-state");
    cleanup();
    renderAdmin(
      <DomainsPage />,
      fakeFetch(() => problem(403, "forbidden", "deployment_scope_required")).impl,
    );
    await screen.findByTestId("forbidden-state");
    cleanup();
    renderAdmin(
      <DomainsPage />,
      fakeFetch(() => problem(500, "dependency_transient", "down")).impl,
    );
    await screen.findByTestId("unavailable-state");
  });
});
