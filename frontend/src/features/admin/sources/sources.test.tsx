import { cleanup, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeAll, describe, expect, it } from "vitest";
import {
  fakeFetch,
  problem,
  renderAdmin,
  stubResizeObserver,
  type FakeRequest,
} from "../shared/test-support";
import { connectorPaths, producerPaths } from "./apiPaths";
import { ConnectorsPage, parseSettings } from "./ConnectorsPage";
import { credentialProblem } from "./credentialReference";
import { ProducersPage, parseSources } from "./ProducersPage";
import type { ConnectorView, ProducerView } from "./types";

beforeAll(stubResizeObserver);
afterEach(cleanup);

const SECRET = "SYNTHETICsecretValueForTestsOnly0123456789abcdefghij";
const FINANCE = "commercial:e2e:catalog:domain:finance";

const PRODUCER: ProducerView = {
  producer_id: "ingest-a",
  customer_id: "e2e",
  cloud: "commercial",
  sources: [{ source_id: "apim-main", observation_kind: "gateway" }],
  status: "active",
  rotated_at: null,
  version: 1,
  updated_at: "2026-11-10T09:00:00Z",
};

function dialog() {
  return within(screen.getByTestId("change-confirm-dialog"));
}
function submit(): HTMLElement {
  return dialog().getByRole("button", { name: "Confirm change", hidden: true });
}

function issued(secret: string) {
  return {
    schema_version: "1.0.0",
    producer_id: "ingest-b",
    secret,
    secret_sha256: "a".repeat(64),
    issued_at: "2026-11-12T10:00:00Z",
    shown_once: true,
  };
}

describe("parseSources", () => {
  it("accepts source and kind lines and rejects anything else", () => {
    expect(parseSources("apim-main gateway\napp-1 application")).toEqual({
      "apim-main": "gateway",
      "app-1": "application",
    });
    expect(parseSources("apim-main")).toBeUndefined();
    expect(parseSources("apim-main nonsense")).toBeUndefined();
    expect(parseSources("")).toBeUndefined();
  });
});

describe("ProducersPage", () => {
  it("lists producers with status and rotation", async () => {
    const { impl } = fakeFetch(() => ({ body: { items: [PRODUCER], truncated: false } }));
    renderAdmin(<ProducersPage />, impl);
    expect(await screen.findAllByTestId("producer-row")).toHaveLength(1);
    expect(screen.getByText("Never rotated")).toBeTruthy();
  });

  it("shows loading, empty, error and forbidden states", async () => {
    const empty = fakeFetch(() => ({ body: { items: [], truncated: false } }));
    renderAdmin(<ProducersPage />, empty.impl);
    expect(screen.getByTestId("loading-state")).toBeTruthy();
    expect(await screen.findByTestId("empty-state")).toBeTruthy();
    cleanup();
    const denied = fakeFetch(() => problem(403, "forbidden", "permission_missing"));
    renderAdmin(<ProducersPage />, denied.impl);
    expect(await screen.findByTestId("forbidden-state")).toBeTruthy();
    cleanup();
    const broken = fakeFetch(() => ({ status: 500, body: { detail: "boom" } }));
    renderAdmin(<ProducersPage />, broken.impl);
    expect(await screen.findByTestId("unavailable-state")).toBeTruthy();
  });

  it("shows the secret once, then clears it from the DOM and the cache", async () => {
    const { impl, calls } = fakeFetch((req) => {
      if (req.method === "POST") return { status: 201, body: issued(SECRET) };
      return { body: { items: [PRODUCER], truncated: false } };
    });
    const { container } = renderAdmin(<ProducersPage />, impl);
    await userEvent.click(await screen.findByRole("button", { name: "Create producer" }));
    expect(submit().hasAttribute("disabled")).toBe(true);
    await userEvent.type(dialog().getByLabelText(/Producer id/), "ingest-b");
    await userEvent.type(dialog().getByLabelText(/Sources/), "apim-main gateway");
    await userEvent.click(submit());
    const secret = await screen.findByTestId("secret-value");
    expect(secret.textContent).toBe(SECRET);
    // The request never put the secret in a URL.
    expect(calls.every((c) => !c.url.toString().includes(SECRET))).toBe(true);
    await userEvent.click(screen.getByRole("button", { name: "I stored it" }));
    await waitFor(() => expect(screen.queryByTestId("secret-dialog")).toBeNull());
    expect(document.body.textContent).not.toContain(SECRET);
    expect(container.innerHTML).not.toContain(SECRET);
  });

  it("rotates after reading the ETag and sends If-Match", async () => {
    const { impl, calls } = fakeFetch((req) => {
      if (req.method === "POST") return { body: issued(SECRET) };
      if (req.url.pathname === producerPaths.one("ingest-a")) {
        return { body: PRODUCER, headers: { ETag: '"producer-1"' } };
      }
      return { body: { items: [PRODUCER], truncated: false } };
    });
    renderAdmin(<ProducersPage />, impl);
    await userEvent.click(await screen.findByRole("button", { name: "Rotate secret ingest-a" }));
    await screen.findByTestId("change-confirm-dialog");
    expect(dialog().getByTestId("change-version").textContent).toBe('"producer-1"');
    await userEvent.click(submit());
    expect((await screen.findByTestId("secret-value")).textContent).toBe(SECRET);
    const post = calls.find((c: FakeRequest) => c.method === "POST");
    expect(post?.headers.get("If-Match")).toBe('"producer-1"');
  });

  it("disables a producer and shows a 409 as stale", async () => {
    const { impl } = fakeFetch((req) => {
      if (req.method === "POST") return problem(409, "stale_version", "etag_mismatch");
      if (req.url.pathname === producerPaths.one("ingest-a")) {
        return { body: PRODUCER, headers: { ETag: '"producer-1"' } };
      }
      return { body: { items: [PRODUCER], truncated: false } };
    });
    renderAdmin(<ProducersPage />, impl);
    await userEvent.click(await screen.findByRole("button", { name: "Disable ingest-a" }));
    await screen.findByTestId("change-confirm-dialog");
    await userEvent.click(submit());
    expect(await dialog().findByText(/changed since you loaded it/)).toBeTruthy();
  });
});

const CONNECTOR: ConnectorView = {
  connector_id: "gw-poll-main",
  connector_kind: "gateway_poll",
  domain_ids: [FINANCE],
  settings: { poll_interval_seconds: 300 },
  credential: {
    kind: "key_vault_secret",
    secret_uri: "https://kv-e2e.vault.azure.net/secrets/gw-poll",
  },
  enabled: true,
  status: "active",
  version: 1,
  updated_at: "2026-11-10T09:00:00Z",
  updated_by: "psn-x",
  warnings: ["producer_not_in_store"],
};

describe("credential and settings parsing", () => {
  it("accepts references and refuses secret-looking values", () => {
    expect(
      credentialProblem({
        kind: "key_vault_secret",
        value: "https://kv-e2e.vault.azure.net/secrets/gw-poll",
      }),
    ).toBeUndefined();
    expect(
      credentialProblem({ kind: "key_vault_secret", value: "hunter2-super-secret-value" }),
    ).toContain("never accepted");
    expect(
      credentialProblem({
        kind: "managed_identity",
        value: "11111111-1111-4111-8111-111111111111",
      }),
    ).toBeUndefined();
    expect(credentialProblem({ kind: "managed_identity", value: "abc" })).toBeDefined();
  });

  it("parses scalar settings", () => {
    expect(parseSettings("poll_interval_seconds=300\nregion=eastus\nverbose=true")).toEqual({
      poll_interval_seconds: 300,
      region: "eastus",
      verbose: true,
    });
    expect(parseSettings("Bad Name=1")).toBeUndefined();
    expect(parseSettings("no equals")).toBeUndefined();
  });
});

describe("ConnectorsPage", () => {
  const readable = {
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
  function handler(extra?: (req: FakeRequest) => ReturnType<Parameters<typeof fakeFetch>[0]>) {
    return (req: FakeRequest) => {
      const custom = extra?.(req);
      if (custom !== undefined) return custom;
      if (req.url.pathname === "/api/v1/me/domains") return { body: readable };
      if (req.url.pathname === connectorPaths.one("gw-poll-main")) {
        return { body: CONNECTOR, headers: { ETag: '"connector-1"' } };
      }
      return { body: { items: [CONNECTOR] } };
    };
  }

  it("lists connectors with the credential reference and warnings, plus the restart note", async () => {
    const { impl } = fakeFetch(handler());
    renderAdmin(<ConnectorsPage />, impl);
    expect(await screen.findAllByTestId("connector-row")).toHaveLength(1);
    expect(screen.getByText(/Key Vault: https:\/\/kv-e2e/)).toBeTruthy();
    expect(screen.getByText("producer_not_in_store")).toBeTruthy();
    expect(screen.getByTestId("restart-note").textContent).toContain("Key Vault Secrets User");
  });

  it("blocks a value pasted into the credential field and sends nothing", async () => {
    const { impl, calls } = fakeFetch(handler());
    renderAdmin(<ConnectorsPage />, impl);
    await userEvent.click(await screen.findByRole("button", { name: "Create connector" }));
    await userEvent.type(dialog().getByLabelText(/Connector id/), "gw-two");
    await userEvent.click(await dialog().findByLabelText(/Finance/));
    await userEvent.selectOptions(dialog().getByLabelText("Credential type"), "key_vault_secret");
    await userEvent.type(
      dialog().getByLabelText(/Key Vault secret URI/),
      "hunter2-not-a-reference",
    );
    expect(await dialog().findByText(/never accepted/)).toBeTruthy();
    expect(submit().hasAttribute("disabled")).toBe(true);
    expect(calls.some((c) => c.method === "POST")).toBe(false);
  });

  it("renders the API 422 when a bad reference is sent anyway", async () => {
    const { impl } = fakeFetch(
      handler((req) =>
        req.method === "POST"
          ? problem(422, "invalid_schema", "/body/credential/secret_uri: not a reference")
          : undefined,
      ),
    );
    renderAdmin(<ConnectorsPage />, impl);
    await userEvent.click(await screen.findByRole("button", { name: "Create connector" }));
    await userEvent.type(dialog().getByLabelText(/Connector id/), "gw-two");
    await userEvent.click(await dialog().findByLabelText(/Finance/));
    await userEvent.click(submit());
    expect(await dialog().findByText(/not a reference/)).toBeTruthy();
  });

  it("creates a connector and shows the warnings the API returned", async () => {
    const { impl, calls } = fakeFetch(
      handler((req) =>
        req.method === "POST"
          ? {
              status: 201,
              body: { ...CONNECTOR, connector_id: "gw-two", warnings: ["producer_not_in_store"] },
            }
          : undefined,
      ),
    );
    renderAdmin(<ConnectorsPage />, impl);
    await userEvent.click(await screen.findByRole("button", { name: "Create connector" }));
    await userEvent.type(dialog().getByLabelText(/Connector id/), "gw-two");
    await userEvent.click(await dialog().findByLabelText(/Finance/));
    await userEvent.click(submit());
    expect(await screen.findByTestId("connector-warnings")).toBeTruthy();
    const post = calls.find((c) => c.method === "POST");
    expect(post?.body).toMatchObject({ connector_id: "gw-two", credential: null, enabled: true });
  });

  it("retires with If-Match", async () => {
    const { impl, calls } = fakeFetch(
      handler((req) =>
        req.method === "DELETE" ? { body: { ...CONNECTOR, status: "retired" } } : undefined,
      ),
    );
    renderAdmin(<ConnectorsPage />, impl);
    await userEvent.click(await screen.findByRole("button", { name: "Retire gw-poll-main" }));
    await screen.findByTestId("change-confirm-dialog");
    await userEvent.click(submit());
    await screen.findByTestId("change-done");
    expect(calls.find((c) => c.method === "DELETE")?.headers.get("If-Match")).toBe('"connector-1"');
  });
});
