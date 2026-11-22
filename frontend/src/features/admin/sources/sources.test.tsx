import { cleanup, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import {
  FluentProvider,
  teamsHighContrastTheme,
  webDarkTheme,
  webLightTheme,
} from "@fluentui/react-components";
import { axe } from "vitest-axe";
import { afterEach, beforeAll, describe, expect, it } from "vitest";
import {
  fakeFetch,
  problem,
  renderAdmin,
  stubResizeObserver,
  type FakeRequest,
} from "../shared/test-support";
import { SOURCES_STATUS_PATH, connectorPaths, producerPaths } from "./apiPaths";
import { ConnectorsPage, parseSettings } from "./ConnectorsPage";
import { credentialProblem } from "./credentialReference";
import { ProducersPage, parseSources } from "./ProducersPage";
import { SOURCE_STRINGS } from "./strings";
import type { ConnectorRunRow, ConnectorView, ProducerView, SourcesAdminStatus } from "./types";

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

const STAMP = "2026-11-20T09:00:00Z";
const STATUS: SourcesAdminStatus = {
  sources: [
    { source: "foundry", state: "connected", last_success_at: STAMP, available: true },
    { source: "apim_gateway", state: "connected", last_success_at: STAMP, available: true },
    { source: "billing", state: "connected", last_success_at: STAMP, available: true },
    {
      source: "azure_monitor_telemetry",
      state: "not_connected",
      last_success_at: null,
      available: true,
    },
  ],
  connectors: [
    {
      kind: "gateway_poll",
      state: "ok",
      reason: null,
      last_success_at: STAMP,
      last_attempt_at: STAMP,
      counts: { gateways_polled: 1 },
    },
  ],
};

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
      if (req.url.pathname === SOURCES_STATUS_PATH) return { body: STATUS };
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

describe("ConnectorsPage first sources and run status", () => {
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
  function world(opts: {
    status?: SourcesAdminStatus | "denied" | "broken";
    items?: ConnectorView[];
  }) {
    return fakeFetch((req) => {
      if (req.url.pathname === "/api/v1/me/domains") return { body: readable };
      if (req.url.pathname === SOURCES_STATUS_PATH) {
        if (opts.status === "denied") return problem(403, "forbidden", "permission_missing");
        if (opts.status === "broken") return { status: 500, body: { detail: "boom" } };
        return { body: opts.status ?? STATUS };
      }
      return { body: { items: opts.items ?? [CONNECTOR] } };
    });
  }
  const failedRun = (kind: ConnectorRunRow["kind"], reason: string | null): ConnectorRunRow => ({
    kind,
    state: "failed",
    reason,
    last_success_at: null,
    last_attempt_at: STAMP,
    counts: {},
  });

  it("lists the four sources, each with Connect, and the Azure Monitor access note", async () => {
    const { impl } = world({});
    renderAdmin(<ConnectorsPage />, impl);
    const panel = await screen.findByTestId("first-sources-panel");
    expect(within(panel).getByText("Azure AI Foundry")).toBeTruthy();
    expect(within(panel).getByText("API Management AI gateways")).toBeTruthy();
    expect(within(panel).getByText("Cost and billing")).toBeTruthy();
    const monitor = within(panel).getByTestId("source-row-azure_monitor_telemetry");
    expect(monitor.textContent).not.toContain("not available in this release");
    expect(monitor.textContent).toContain("Log Analytics Data Reader");
    expect(monitor.textContent).toContain("Privileged Monitoring Data Reader");
    expect(monitor.textContent).toContain("owner of the workspace approves");
    expect(within(panel).getAllByText("Connected").length).toBe(3);
    expect(within(panel).getAllByText(STAMP).length).toBe(3);
    for (const name of [
      "Azure AI Foundry",
      "API Management AI gateways",
      "Cost and billing",
      "Azure Monitor and Application Insights",
    ]) {
      expect(within(panel).getByRole("button", { name: `Connect ${name}` })).toBeTruthy();
    }
    expect(panel.textContent).toContain("no key or connection string");
  });

  it("shows all four with Connect when nothing is configured, and pre-sets the kind", async () => {
    const none: SourcesAdminStatus = {
      sources: STATUS.sources.map((r) => ({ ...r, state: "not_connected", last_success_at: null })),
      connectors: [],
    };
    const { impl } = world({ status: none, items: [] });
    renderAdmin(<ConnectorsPage />, impl);
    const panel = await screen.findByTestId("first-sources-panel");
    expect(screen.queryAllByTestId("connector-row")).toHaveLength(0);
    expect(within(panel).getAllByText("Not connected").length).toBe(4);
    expect(within(panel).getAllByRole("button", { name: /^Connect / })).toHaveLength(4);
    await userEvent.click(within(panel).getByRole("button", { name: "Connect Cost and billing" }));
    await screen.findByTestId("change-confirm-dialog");
    const kind = dialog().getByLabelText(/Connector kind/) as HTMLSelectElement;
    expect(kind.value).toBe("billing_export");
  });

  it("pre-sets azure_monitor_ai and its settings template from the Azure Monitor Connect", async () => {
    const { impl } = world({ items: [] });
    renderAdmin(<ConnectorsPage />, impl);
    await userEvent.click(
      await screen.findByRole("button", { name: "Connect Azure Monitor and Application Insights" }),
    );
    await screen.findByTestId("change-confirm-dialog");
    expect((dialog().getByLabelText(/Connector kind/) as HTMLSelectElement).value).toBe(
      "azure_monitor_ai",
    );
    const settings = dialog().getByLabelText(/Settings/) as HTMLTextAreaElement;
    expect(settings.value).toContain("interval_seconds=300");
    expect(settings.value).toContain("producer_id=azure-monitor-ai");
    expect(
      dialog().getByText(/workspace_ids \(1 to 4 workspace GUIDs/, { exact: false }),
    ).toBeTruthy();
  });

  it("renders the Azure Monitor reason codes in plain language", async () => {
    const codes = [
      "query_budget_exhausted",
      "event_budget_exhausted",
      "rate_limited",
      "stalled",
      "ingest_failed",
      "cloud_mismatch",
      "refused_government_unverified",
      "source_unreachable",
      "partial_results",
      "source_access_denied",
    ];
    for (const code of codes) {
      const sentence = SOURCE_STRINGS.reasonText(code, "azure_monitor_ai");
      expect(sentence).not.toBeNull();
      expect(sentence).not.toContain("_");
      expect(sentence).not.toContain("does not describe");
    }
    expect(SOURCE_STRINGS.reasonText("source_access_denied", "azure_monitor_ai")).toContain(
      "Log Analytics Data Reader",
    );
  });

  it("pre-sets foundry_discovery from the Foundry Connect action", async () => {
    const { impl } = world({ items: [] });
    renderAdmin(<ConnectorsPage />, impl);
    await userEvent.click(await screen.findByRole("button", { name: "Connect Azure AI Foundry" }));
    await screen.findByTestId("change-confirm-dialog");
    expect((dialog().getByLabelText(/Connector kind/) as HTMLSelectElement).value).toBe(
      "foundry_discovery",
    );
  });

  it("renders the missing role and resource kind for source_access_denied", async () => {
    const rows = [
      failedRun("foundry_discovery", "source_access_denied"),
      failedRun("gateway_poll", "source_access_denied"),
      failedRun("billing_export", "source_access_denied"),
    ];
    const items: ConnectorView[] = [
      { ...CONNECTOR, connector_id: "f1", connector_kind: "foundry_discovery" },
      { ...CONNECTOR, connector_id: "g1" },
      { ...CONNECTOR, connector_id: "b1", connector_kind: "billing_export" },
    ];
    const { impl } = world({ status: { sources: STATUS.sources, connectors: rows }, items });
    renderAdmin(<ConnectorsPage />, impl);
    const reasons = await screen.findAllByTestId("run-reason");
    const text = reasons.map((r) => r.textContent ?? "");
    expect(text[0]).toContain("Foundry User is missing on the Foundry account");
    expect(text[1]).toContain("Log Analytics Data Reader");
    expect(text[1]).toContain("Log Analytics workspace");
    expect(text[1]).toContain("API Management Service Reader on the API Management service");
    expect(text[2]).toContain("Storage Blob Data Reader");
    expect(text[2]).toContain("export storage account");
    for (const t of text) expect(t).toContain("approve the access");
  });

  it("gives an unknown reason code a generic sentence, never the raw code", async () => {
    const { impl } = world({
      status: { sources: STATUS.sources, connectors: [failedRun("gateway_poll", "zz_new_code")] },
    });
    renderAdmin(<ConnectorsPage />, impl);
    const reason = await screen.findByTestId("run-reason");
    expect(reason.textContent).not.toContain("zz_new_code");
    expect(reason.textContent).toContain("does not describe");
  });

  it("gives every known reason code a sentence", () => {
    const codes = [
      "source_unreachable",
      "partial_results",
      "ingest_failed",
      "cloud_not_supported",
      "incomplete_export",
      "unchanged",
      "tick_error",
      "awaiting_first_run",
    ];
    for (const code of codes) {
      const sentence = SOURCE_STRINGS.reasonText(code, "gateway_poll");
      expect(sentence).not.toBeNull();
      expect(sentence).not.toContain("_");
    }
  });

  it("keeps the page working when the admin status is denied or broken", async () => {
    for (const status of ["denied", "broken"] as const) {
      const { impl } = world({ status });
      renderAdmin(<ConnectorsPage />, impl);
      expect(await screen.findAllByTestId("connector-row")).toHaveLength(1);
      expect(await screen.findByText("Status unavailable")).toBeTruthy();
      expect(screen.getByTestId("status-unavailable-note")).toBeTruthy();
      expect(screen.getAllByRole("button", { name: /^Connect / })).toHaveLength(4);
      expect(screen.queryByTestId("forbidden-state")).toBeNull();
      expect(screen.queryByTestId("unavailable-state")).toBeNull();
      cleanup();
    }
  });

  it("passes axe in three themes with state in words", async () => {
    for (const theme of [webLightTheme, webDarkTheme, teamsHighContrastTheme]) {
      const { impl } = world({
        status: {
          sources: STATUS.sources,
          connectors: [failedRun("gateway_poll", "source_access_denied")],
        },
      });
      const { container } = renderAdmin(
        <FluentProvider theme={theme}>
          <ConnectorsPage />
        </FluentProvider>,
        impl,
      );
      await screen.findByTestId("run-status");
      expect(screen.getByText("Failed")).toBeTruthy();
      const violations = (await axe(container)).violations.map((v) => `${v.id}: ${v.help}`);
      expect(violations).toEqual([]);
      cleanup();
    }
  });

  it("adds no secret field to the page", async () => {
    const { impl } = world({});
    const { container } = renderAdmin(<ConnectorsPage />, impl);
    await screen.findByTestId("first-sources-panel");
    expect(container.querySelectorAll("input[type=password]")).toHaveLength(0);
  });
});

describe("ProducersPage empty state", () => {
  it("links to the Connectors panel", async () => {
    const { impl } = fakeFetch(() => ({ body: { items: [], truncated: false } }));
    renderAdmin(<ProducersPage />, impl);
    const link = await screen.findByTestId("empty-connectors-link");
    expect(link.getAttribute("href")).toBe("/admin/sources/connectors#first-sources");
  });
});
