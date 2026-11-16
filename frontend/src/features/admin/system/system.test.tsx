import { cleanup, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeAll, describe, expect, it } from "vitest";
import { fakeFetch, problem, renderAdmin, stubResizeObserver } from "../shared/test-support";
import { SystemPage } from "./SystemPage";

beforeAll(stubResizeObserver);
afterEach(cleanup);

const SECRET = "https://probe-secret-host.invalid/key=s3cr3t-value";
const STORED = { status: "loaded", reason: null, invalid_keys: [] };

function ok(overrides: { settings?: unknown } = {}) {
  return fakeFetch((req) => {
    if (req.url.pathname.endsWith("/status")) {
      return {
        body: {
          ready: false,
          probes: { cosmos: SECRET },
          stored_settings: STORED,
          components: [
            {
              name: "authz",
              state: "ok",
              required: true,
              reason: null,
              blocks_readiness: false,
              step: false,
            },
            {
              name: "ingest",
              state: "failed",
              required: true,
              reason: "ingest_producers_unconfigured",
              blocks_readiness: true,
              step: false,
              host: SECRET,
            },
            {
              name: "scan",
              state: "not_built",
              required: false,
              reason: "not_built",
              blocks_readiness: false,
              step: false,
            },
          ],
        },
      };
    }
    if (req.url.pathname.endsWith("/checklist")) {
      return {
        body: {
          items: [
            {
              item_id: "stored_settings.store",
              component: "admin_config",
              status: "complete",
              reason: null,
              doc_path: "docs/runbooks/system-settings.md#stored",
              required: true,
            },
            {
              item_id: "ingest.producers",
              component: "ingest",
              status: "missing",
              reason: "ingest_producers_unconfigured",
              doc_path: null,
              required: true,
            },
            {
              item_id: "write_targets.registered",
              component: "write_targets",
              status: "error",
              reason: "write_targets_stored_not_registered",
              doc_path: null,
              required: true,
            },
            {
              item_id: "auth.customer_binding",
              component: "authz",
              status: "not_applicable",
              reason: "local_default_customer",
              doc_path: null,
              required: true,
            },
          ],
        },
      };
    }
    if (req.url.pathname.endsWith("/settings")) {
      return { body: overrides.settings };
    }
    return undefined;
  });
}

const SETTINGS = {
  stored_settings: STORED,
  items: [
    {
      key: "copilot",
      source: "stored",
      stored_revision: 3,
      applied_revision: 2,
      restart_required: true,
      applied_by_runtime: true,
      etag: null,
      entries: [
        {
          document_id: "copilot",
          version: 1,
          etag: "e",
          value: { endpoint: SECRET, extra: SECRET },
        },
      ],
    },
    {
      key: "judge",
      source: "env",
      stored_revision: null,
      applied_revision: null,
      restart_required: false,
      applied_by_runtime: true,
      etag: null,
      entries: [],
    },
    {
      key: "scan",
      source: "default",
      stored_revision: null,
      applied_revision: null,
      restart_required: false,
      applied_by_runtime: true,
      etag: null,
      entries: [],
    },
  ],
};

describe("SystemPage", () => {
  it("shows components, checklist and settings with source and restart state", async () => {
    renderAdmin(<SystemPage />, ok({ settings: SETTINGS }).impl);
    expect(await screen.findAllByTestId("component-row")).toHaveLength(3);
    expect(screen.getByTestId("ready-state").textContent).toBe("The deployment reports not ready.");
    const checklist = await screen.findAllByTestId("checklist-row");
    expect(checklist).toHaveLength(4);
    expect(checklist[0]?.textContent).toContain("Done");
    expect(checklist[1]?.textContent).toContain("To do");
    expect(checklist[2]?.textContent).toContain("Blocked");
    expect(checklist[3]?.textContent).toContain("Not applicable");
    expect(checklist[0]?.textContent).toContain("docs/runbooks/system-settings.md#stored");
    const settings = await screen.findAllByTestId("setting-row");
    expect(settings).toHaveLength(3);
    expect(settings[0]?.textContent).toContain("Stored");
    expect(settings[0]?.textContent).toContain("Restart required");
    expect(settings[1]?.textContent).toContain("Environment");
    expect(settings[2]?.textContent).toContain("Default");
  });

  it("never renders a configuration value, host or secret from the response", async () => {
    renderAdmin(<SystemPage />, ok({ settings: SETTINGS }).impl);
    await screen.findAllByTestId("setting-row");
    const text = document.body.textContent ?? "";
    expect(text).not.toContain("probe-secret-host");
    expect(text).not.toContain("s3cr3t-value");
    expect(text).not.toContain("endpoint");
  });

  it("shows empty, forbidden and unavailable states", async () => {
    renderAdmin(<SystemPage />, ok({ settings: { items: [], stored_settings: STORED } }).impl);
    await screen.findByTestId("empty-state");
    cleanup();
    renderAdmin(
      <SystemPage />,
      fakeFetch(() => problem(403, "forbidden", "deployment_scope_required")).impl,
    );
    await waitFor(() => expect(screen.getAllByTestId("panel-denied")).toHaveLength(2));
    cleanup();
    renderAdmin(<SystemPage />, fakeFetch(() => problem(503, "dependency_transient", "down")).impl);
    await waitFor(() => expect(screen.getAllByTestId("unavailable-state")).toHaveLength(3));
  });

  it("shows loading first", () => {
    renderAdmin(<SystemPage />, (() => new Promise<Response>(() => undefined)) as typeof fetch);
    expect(screen.getAllByTestId("loading-state").length).toBe(3);
  });
});
