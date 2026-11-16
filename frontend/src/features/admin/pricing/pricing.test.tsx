import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeAll, describe, expect, it } from "vitest";
import { fakeFetch, problem, renderAdmin, stubResizeObserver } from "../shared/test-support";
import { isDecimalAmount, parseThresholds, showAmount } from "./decimal";
import { PricingPage } from "./PricingPage";
import { parseRows } from "./PriceSheetsPanel";

beforeAll(stubResizeObserver);
afterEach(cleanup);

const FINANCE = "commercial:e2e:catalog:domain:finance";
const SHEETS = {
  items: [
    {
      snapshot_id: "azure-2026-10",
      source: "provider_price_sheet",
      source_url: "https://p.invalid/x",
      retrieval_date: "2026-10-02",
      effective_date: "2026-10-01",
      currency: "USD",
      clouds: ["commercial"],
      synthetic: true,
      content_hash: "h1",
      row_count: 1,
      notes: "",
    },
    {
      snapshot_id: "azure-2026-11",
      source: "provider_price_sheet",
      source_url: "https://p.invalid/x",
      retrieval_date: "2026-11-02",
      effective_date: "2026-11-01",
      currency: "USD",
      clouds: ["commercial"],
      synthetic: true,
      content_hash: "h2",
      row_count: 2,
      notes: "",
    },
  ],
};
const BUDGET = {
  budget_id: "finance-monthly",
  domain_id: FINANCE,
  period: "monthly",
  amount: "0.1",
  currency: "USD",
  thresholds_percent: [50, 100],
  tags_filter: null,
  status: "active",
  version: 1,
  updated_at: "x",
  updated_by: "y",
};
const DOMAINS = {
  items: [
    {
      domain_id: FINANCE,
      display_name: "Finance",
      display_name_source: "catalog",
      cloud: "commercial",
      permissions: [],
    },
  ],
};

function dialog() {
  return within(screen.getByTestId("change-confirm-dialog"));
}

describe("decimal helpers", () => {
  it("never convert to a float", () => {
    expect(isDecimalAmount("0.1")).toBe(true);
    expect(isDecimalAmount("1e3")).toBe(false);
    expect(isDecimalAmount("-1")).toBe(false);
    expect(isDecimalAmount("0.1234567890123")).toBe(false);
    // 0.1 + 0.2 as strings stays as received.
    expect(showAmount("0.300000000004")).toBe("0.300000000004");
    expect(showAmount(null)).toBe("Unknown");
    expect(showAmount("0")).toBe("0");
    expect(parseThresholds("50, 80,100")).toEqual([50, 80, 100]);
    expect(parseThresholds("0")).toBeUndefined();
  });

  it("rows must carry decimal strings", () => {
    expect(parseRows('[{"retail_price":"0.0015"}]')).toHaveLength(1);
    expect(parseRows('[{"retail_price":0.0015}]')).toBeUndefined();
    expect(parseRows("[]")).toBeUndefined();
  });
});

describe("PricingPage", () => {
  function handler(extra?: Parameters<typeof fakeFetch>[0]) {
    return (req: Parameters<Parameters<typeof fakeFetch>[0]>[0]) => {
      const custom = extra?.(req);
      if (custom !== undefined) return custom;
      if (req.url.pathname === "/api/v1/me/domains") return { body: DOMAINS };
      if (req.url.pathname.endsWith("/price-sheets")) return { body: SHEETS };
      if (req.url.pathname.endsWith("/budgets/finance-monthly")) {
        return { body: BUDGET, headers: { ETag: '"budget-1"' } };
      }
      if (req.url.pathname.endsWith("/budgets")) return { body: { items: [BUDGET] } };
      return undefined;
    };
  }

  it("marks the newest price sheet and lists budgets with decimal amounts as received", async () => {
    const { impl } = fakeFetch(handler());
    renderAdmin(<PricingPage />, impl);
    const rows = await screen.findAllByTestId("price-sheet-row");
    expect(rows).toHaveLength(2);
    expect(within(rows[1] as HTMLElement).getByText("Newest")).toBeTruthy();
    expect((await screen.findAllByTestId("budget-row"))[0]?.textContent).toContain("0.1 USD");
  });

  it("shows unavailable and forbidden states per panel", async () => {
    const { impl } = fakeFetch(() => problem(403, "forbidden", "permission_missing"));
    renderAdmin(<PricingPage />, impl);
    await waitFor(() => expect(screen.getAllByTestId("forbidden-state")).toHaveLength(2));
  });

  it(
    "uploads a price sheet and shows the API field pointer for a bad row",
    { timeout: 30000 },
    async () => {
      let reject = true;
      const { impl, calls } = fakeFetch(
        handler((req) => {
          if (req.method !== "POST" || !req.url.pathname.endsWith("/price-sheets"))
            return undefined;
          if (reject) {
            reject = false;
            return problem(422, "invalid_schema", "/body/rows/0/retail_price: bad");
          }
          return {
            status: 201,
            body: {
              created: true,
              sheet: SHEETS.items[1],
              coverage: {
                snapshot_id: "s",
                rows: 1,
                models_priced: 1,
                models_incomplete: [],
                rows_without_token_meter: 0,
                warnings: [],
              },
            },
          };
        }),
      );
      renderAdmin(<PricingPage />, impl);
      await screen.findAllByTestId("price-sheet-row");
      fireEvent.change(screen.getByLabelText(/Snapshot id/), {
        target: { value: "azure-2026-12" },
      });
      fireEvent.change(screen.getByLabelText(/Source URL/), {
        target: { value: "https://prices.example.invalid/s" },
      });
      fireEvent.change(screen.getByLabelText(/Retrieval date/), {
        target: { value: "2026-12-02" },
      });
      fireEvent.change(screen.getByLabelText(/Effective date/), {
        target: { value: "2026-12-01" },
      });
      const submitButton = screen.getByRole("button", { name: "Upload price sheet" });
      expect(submitButton.hasAttribute("disabled")).toBe(true);
      fireEvent.change(screen.getByLabelText(/Rows \(JSON array\)/), {
        target: {
          value:
            '[{"service_name":"s","sku_name":"k","unit_of_measure":"1K","retail_price":"0.300000000004"}]',
        },
      });
      expect(submitButton.hasAttribute("disabled")).toBe(false);
      await userEvent.click(submitButton);
      expect((await screen.findByTestId("upload-error")).textContent).toContain(
        "rows/0/retail_price",
      );
      await userEvent.click(submitButton);
      expect((await screen.findByTestId("upload-done")).textContent).toContain("created");
      const post = calls.filter((c) => c.method === "POST").at(-1);
      expect((post?.body as { rows: { retail_price: string }[] }).rows[0]?.retail_price).toBe(
        "0.300000000004",
      );
    },
  );

  it("creates a budget and sends the amount as a decimal string", async () => {
    const { impl, calls } = fakeFetch(
      handler((req) =>
        req.method === "POST" && req.url.pathname.endsWith("/budgets")
          ? { status: 201, body: BUDGET }
          : undefined,
      ),
    );
    renderAdmin(<PricingPage />, impl);
    await userEvent.click(await screen.findByRole("button", { name: "Create budget" }));
    await userEvent.type(dialog().getByLabelText(/Budget id/), "ops-monthly");
    await userEvent.type(dialog().getByLabelText(/Amount/), "1e3");
    expect(await dialog().findByText(/plain decimal/)).toBeTruthy();
    await userEvent.clear(dialog().getByLabelText(/Amount/));
    await userEvent.type(dialog().getByLabelText(/Amount/), "2500.50");
    await userEvent.click(dialog().getByRole("button", { name: "Confirm change", hidden: true }));
    await screen.findByTestId("change-done");
    const post = calls.find((c) => c.method === "POST" && c.url.pathname.endsWith("/budgets"));
    expect(post?.body).toMatchObject({
      amount: "2500.50",
      domain_id: FINANCE,
      thresholds_percent: [50, 80, 100],
    });
  });

  it("edits a budget with If-Match and shows stale on 409", async () => {
    const { impl, calls } = fakeFetch(
      handler((req) =>
        req.method === "PUT" ? problem(409, "stale_version", "etag_mismatch") : undefined,
      ),
    );
    renderAdmin(<PricingPage />, impl);
    await userEvent.click(await screen.findByRole("button", { name: "Edit finance-monthly" }));
    await screen.findByTestId("change-confirm-dialog");
    await userEvent.click(dialog().getByRole("button", { name: "Confirm change", hidden: true }));
    expect(await dialog().findByText(/changed since you loaded it/)).toBeTruthy();
    expect(calls.find((c) => c.method === "PUT")?.headers.get("If-Match")).toBe('"budget-1"');
  });
});
