import { cleanup, fireEvent, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeAll, describe, expect, it } from "vitest";
import { fakeFetch, problem, renderAdmin, stubResizeObserver } from "../shared/test-support";
import { CatalogImportPage } from "./CatalogImportPage";
import { canonicalJson, digestOf, parsePayload } from "./importPayload";

beforeAll(stubResizeObserver);
afterEach(cleanup);

function typeJson(text: string): void {
  fireEvent.change(screen.getByLabelText(/Entity documents/), { target: { value: text } });
}

describe("parsePayload", () => {
  it("accepts an array or an items object and gives the same digest for key order", () => {
    const a = parsePayload('[{"id":"a","x":1}]');
    const b = parsePayload('{"items":[{"x":1,"id":"a"}]}');
    expect(a.ok && b.ok && a.digest === b.digest).toBe(true);
    expect(canonicalJson({ b: 1, a: 2 })).toBe('{"a":2,"b":1}');
    expect(digestOf("x")).not.toBe(digestOf("y"));
  });

  it("blocks more than 100 items and non-objects", () => {
    const many = JSON.stringify(Array.from({ length: 101 }, (_, i) => ({ id: String(i) })));
    const result = parsePayload(many);
    expect(result.ok).toBe(false);
    expect(!result.ok && result.error).toContain("limit is 100");
    expect(parsePayload("[1]").ok).toBe(false);
    expect(parsePayload("{").ok).toBe(false);
  });
});

describe("CatalogImportPage", () => {
  it("requires a clean dry run of the same payload before commit", async () => {
    const { impl, calls } = fakeFetch((req) => {
      const body = req.body as { dry_run: boolean; items: unknown[] };
      return {
        body: {
          committed: !body.dry_run,
          dry_run: body.dry_run,
          items: body.items.map((_, index) => ({
            index,
            id: `e${index}`,
            status: body.dry_run ? "valid" : "created",
            code: null,
          })),
        },
      };
    });
    renderAdmin(<CatalogImportPage />, impl);
    const commit = screen.getByRole("button", { name: "Commit import" });
    expect(commit.hasAttribute("disabled")).toBe(true);
    typeJson('[{"id":"a"},{"id":"b"}]');
    expect(commit.hasAttribute("disabled")).toBe(true);
    await userEvent.click(screen.getByRole("button", { name: "Dry run" }));
    expect(await screen.findByText("Dry run is clean: every item is valid.")).toBeTruthy();
    expect(commit.hasAttribute("disabled")).toBe(false);
    // Changing the payload invalidates the dry run.
    typeJson('[{"id":"a"},{"id":"c"}]');
    expect(commit.hasAttribute("disabled")).toBe(true);
    typeJson('[{"id":"a"},{"id":"b"}]');
    await userEvent.click(screen.getByRole("button", { name: "Dry run" }));
    await screen.findByText("Dry run is clean: every item is valid.");
    await userEvent.click(commit);
    expect(await screen.findByText("Import committed.")).toBeTruthy();
    expect(calls.map((c) => (c.body as { dry_run: boolean }).dry_run)).toEqual([true, true, false]);
    expect(screen.getAllByTestId("import-row")).toHaveLength(2);
  });

  it("keeps commit disabled after a dry run with rejected items and shows codes", async () => {
    const { impl } = fakeFetch(() => ({
      body: {
        committed: false,
        dry_run: true,
        items: [
          { index: 0, id: "a", status: "valid", code: null },
          { index: 1, id: null, status: "rejected", code: "missing_id" },
        ],
      },
    }));
    renderAdmin(<CatalogImportPage />, impl);
    typeJson('[{"id":"a"},{"name":"b"}]');
    await userEvent.click(screen.getByRole("button", { name: "Dry run" }));
    expect(await screen.findByText("missing_id")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Commit import" }).hasAttribute("disabled")).toBe(true);
  });

  it("states the limit and sends nothing for an oversized payload", async () => {
    const { impl, calls } = fakeFetch(() => ({ body: {} }));
    renderAdmin(<CatalogImportPage />, impl);
    typeJson(JSON.stringify(Array.from({ length: 101 }, (_, i) => ({ id: String(i) }))));
    expect(await screen.findByText(/limit is 100/)).toBeTruthy();
    expect(screen.getByRole("button", { name: "Dry run" }).hasAttribute("disabled")).toBe(true);
    expect(calls).toHaveLength(0);
  });

  it("renders payload strings as text and shows an API error", async () => {
    const { impl } = fakeFetch(() => problem(403, "forbidden", "permission_missing"));
    renderAdmin(<CatalogImportPage />, impl);
    typeJson('[{"id":"<img src=x onerror=alert(1)>"}]');
    await userEvent.click(screen.getByRole("button", { name: "Dry run" }));
    expect((await screen.findByTestId("import-error")).textContent).toContain("Access denied");
    expect(document.querySelector("img")).toBeNull();
  });
});
