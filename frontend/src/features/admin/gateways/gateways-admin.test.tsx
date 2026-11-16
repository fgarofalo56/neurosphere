import { cleanup, fireEvent, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeAll, describe, expect, it } from "vitest";
import { fakeFetch, problem, renderAdmin, stubResizeObserver } from "../shared/test-support";
import { RegisterGatewayPage } from "./RegisterGatewayPage";

beforeAll(stubResizeObserver);
afterEach(cleanup);

const FINANCE = "commercial:e2e:catalog:domain:finance";
const ARM =
  "/subscriptions/11111111-1111-4111-8111-111111111111/resourceGroups/rg-e2e/providers/Microsoft.ApiManagement/service/apim-e2e";
const DOMAINS = {
  items: [
    {
      domain_id: FINANCE,
      display_name: "Finance",
      display_name_source: "catalog",
      cloud: "commercial",
      permissions: ["data.read"],
    },
  ],
};

describe("RegisterGatewayPage", () => {
  it("registers a gateway and links to its detail page", async () => {
    const { impl, calls } = fakeFetch((req) => {
      if (req.method === "POST") {
        return { status: 201, body: { id: "gw-0123", name: "apim-e2e", domain_id: FINANCE } };
      }
      return { body: DOMAINS };
    });
    renderAdmin(<RegisterGatewayPage />, impl);
    const arm = await screen.findByLabelText(/API Management resource id/);
    const button = screen.getByRole("button", { name: "Register gateway" });
    expect(button.hasAttribute("disabled")).toBe(true);
    await userEvent.type(arm, "not-an-arm-id");
    expect(await screen.findByText(/does not look like/)).toBeTruthy();
    await userEvent.clear(arm);
    await userEvent.type(arm, ARM);
    await userEvent.click(button);
    const done = await screen.findByTestId("register-done");
    expect(done.querySelector("a")?.getAttribute("href")).toContain("/gateways/detail?");
    const post = calls.find((c) => c.method === "POST");
    expect(post?.url.pathname).toBe(
      `/api/v1/gateways/domains/${encodeURIComponent(FINANCE)}/gateways`,
    );
    expect(post?.body).toEqual({ arm_resource_id: ARM });
  });

  it("shows 403, 409 and 422 with their codes", async () => {
    for (const [status, code] of [
      [403, "forbidden"],
      [409, "conflict"],
      [422, "invalid_schema"],
    ] as const) {
      const { impl } = fakeFetch((req) =>
        req.method === "POST" ? problem(status, code, "detail text") : { body: DOMAINS },
      );
      renderAdmin(<RegisterGatewayPage />, impl);
      fireEvent.change(await screen.findByLabelText(/API Management resource id/), {
        target: { value: ARM },
      });
      await userEvent.click(screen.getByRole("button", { name: "Register gateway" }));
      expect((await screen.findByTestId("register-error")).textContent).toContain(code);
      cleanup();
    }
  });

  it("shows a forbidden state when domains cannot be read", async () => {
    const { impl } = fakeFetch(() => problem(403, "forbidden", "permission_missing"));
    renderAdmin(<RegisterGatewayPage />, impl);
    expect(await screen.findByTestId("forbidden-state")).toBeTruthy();
  });
});
