import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeAll, describe, expect, it } from "vitest";
import { fakeFetch, problem, renderAdmin, stubResizeObserver, type FakeRequest } from "../shared/test-support";
import { FeatureSettingsPage } from "./FeatureSettingsPage";
import { SETTING_SPECS, bodyFromDraft, draftFromStored } from "./settingSpecs";

beforeAll(stubResizeObserver);
afterEach(cleanup);

const CLIENT = "11111111-1111-4111-8111-111111111111";
const COPILOT = {
  schema_version: "1.0.0",
  setting_key: "copilot",
  enabled: true,
  copilot: {
    endpoint: "https://oai-e2e.openai.azure.com",
    deployment: "gpt-e2e",
    api_version: "2025-01-01-preview",
    resource_id: null,
    credential: { kind: "managed_identity", managed_identity_client_id: CLIENT },
  },
};

function view(key: string, stored: unknown, etag: string | null) {
  return {
    key,
    source: stored === null ? "default" : "stored",
    stored_revision: stored === null ? null : 3,
    applied_revision: stored === null ? null : 2,
    restart_required: stored !== null,
    applied_by_runtime: true,
    etag,
    entries:
      stored === null
        ? []
        : [{ document_id: `system.${key}`, version: 3, etag: "e", value: stored }],
  };
}

function handler(extra?: (req: FakeRequest) => ReturnType<Parameters<typeof fakeFetch>[0]>) {
  return (req: FakeRequest) => {
    const custom = extra?.(req);
    if (custom !== undefined) return custom;
    const key = req.url.pathname.split("/").at(-1) ?? "";
    if (req.method === "GET") {
      return key === "copilot"
        ? { body: view("copilot", COPILOT, '"s-3"'), headers: { ETag: '"s-3"' } }
        : { body: view(key, key === "write_targets" ? WRITE_TARGET : null, null) };
    }
    return undefined;
  };
}
const WRITE_TARGET = {
  schema_version: "1.0.0",
  setting_key: "write_target",
  enabled: false,
  write_target: { target_kind: "apim", credential: null },
};

describe("settingSpecs", () => {
  it("round-trips a stored value and never emits a credential-named field", () => {
    const spec = SETTING_SPECS.copilot;
    const draft = draftFromStored(spec, COPILOT);
    const body = bodyFromDraft(spec, draft) as Record<string, Record<string, unknown>>;
    expect(body["copilot"]).toMatchObject({
      endpoint: "https://oai-e2e.openai.azure.com",
      credential: { kind: "managed_identity", managed_identity_client_id: CLIENT },
    });
    const names = JSON.stringify(Object.keys(JSON.parse(JSON.stringify(body["copilot"]))));
    expect(names).not.toMatch(/key|secret|password|token/i);
  });
});

describe("FeatureSettingsPage", () => {
  it("shows a card per key with source, revision and restart state", async () => {
    const { impl } = fakeFetch(handler());
    renderAdmin(<FeatureSettingsPage />, impl);
    const cards = await waitFor(() => {
      const all = screen.getAllByTestId("setting-card");
      expect(all).toHaveLength(6);
      return all;
    });
    const copilot = cards.find((c) => c.getAttribute("data-key") === "copilot") as HTMLElement;
    expect(within(copilot).getByTestId("setting-meta").textContent).toContain("stored");
    expect(within(copilot).getByTestId("setting-meta").textContent).toContain("Restart required");
    expect(screen.getByTestId("write-targets-note").textContent).toContain("PRP-54");
  });

  it("offers no secret-looking input anywhere", async () => {
    const { impl } = fakeFetch(handler());
    renderAdmin(<FeatureSettingsPage />, impl);
    await waitFor(() => expect(screen.getAllByTestId("setting-card")).toHaveLength(6));
    for (const input of document.querySelectorAll("input,textarea")) {
      const label = input.getAttribute("aria-label") ?? input.id;
      expect(label).not.toMatch(/api key|password|secret value|token/i);
      expect((input as HTMLInputElement).type).not.toBe("password");
    }
  });

  it("saves with If-Match, shows the diff and the restart notice", async () => {
    const { impl, calls } = fakeFetch(
      handler((req) =>
        req.method === "PUT"
          ? {
              body: {
                key: "copilot",
                document_id: "system.copilot",
                version: 4,
                etag: '"s-4"',
                stored_revision: 4,
                applied_revision: 2,
                restart_required: true,
                diff: [{ pointer: "/copilot/deployment", before: "gpt-e2e", after: "gpt-next" }],
              },
            }
          : undefined,
      ),
    );
    renderAdmin(<FeatureSettingsPage />, impl);
    const deployment = await screen.findByLabelText(/Copilot model Deployment name/);
    fireEvent.change(deployment, { target: { value: "gpt-next" } });
    await userEvent.click(screen.getByRole("button", { name: "Save setting: Copilot model" }));
    const dlg = within(await screen.findByTestId("change-confirm-dialog"));
    expect(dlg.getByTestId("change-diff").textContent).toContain("gpt-next");
    await userEvent.click(dlg.getByRole("button", { name: "Confirm change", hidden: true }));
    const saved = await screen.findByTestId("setting-saved");
    expect(saved.textContent).toContain("applies after the API and workers restart");
    expect(screen.getByTestId("setting-result-diff").textContent).toContain("/copilot/deployment");
    const put = calls.find((c) => c.method === "PUT");
    expect(put?.headers.get("If-Match")).toBe('"s-3"');
    expect(put?.url.pathname).toBe("/api/v1/admin/system/settings/copilot");
  });

  it("shows the validator text on 422 and a stale message on 409", async () => {
    const first = fakeFetch(
      handler((req) =>
        req.method === "PUT" ? problem(422, "invalid_schema", "endpoint belongs to another cloud") : undefined,
      ),
    );
    renderAdmin(<FeatureSettingsPage />, first.impl);
    fireEvent.change(await screen.findByLabelText(/Copilot model Deployment name/), {
      target: { value: "x" },
    });
    await userEvent.click(screen.getByRole("button", { name: "Save setting: Copilot model" }));
    const dlg = within(await screen.findByTestId("change-confirm-dialog"));
    await userEvent.click(dlg.getByRole("button", { name: "Confirm change", hidden: true }));
    expect((await screen.findByTestId("setting-error")).textContent).toContain("another cloud");
    cleanup();
    const second = fakeFetch(
      handler((req) => (req.method === "PUT" ? problem(409, "stale_version", "etag_mismatch") : undefined)),
    );
    renderAdmin(<FeatureSettingsPage />, second.impl);
    fireEvent.change(await screen.findByLabelText(/Copilot model Deployment name/), {
      target: { value: "y" },
    });
    await userEvent.click(screen.getByRole("button", { name: "Save setting: Copilot model" }));
    const dlg2 = within(await screen.findByTestId("change-confirm-dialog"));
    await userEvent.click(dlg2.getByRole("button", { name: "Confirm change", hidden: true }));
    expect((await screen.findByTestId("setting-error")).textContent).toContain("Reload and try again");
  });

  it("shows forbidden per card", async () => {
    const { impl } = fakeFetch(() => problem(403, "forbidden", "permission_missing"));
    renderAdmin(<FeatureSettingsPage />, impl);
    await waitFor(() => expect(screen.getAllByTestId("forbidden-state")).toHaveLength(6));
  });
});
