import "@testing-library/jest-dom/vitest";
import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { createMemoryRouter, RouterProvider } from "react-router";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import { axe } from "vitest-axe";
import { QueryProvider, createApiClient } from "../../api/index.js";
import { toUtc } from "./hooks";
import { caseRefProblem } from "./PurposeFields";
import { interactionsRoutes } from "./routes";
import { STRINGS } from "./strings";
import type {
  InteractionExportManifest,
  InteractionPage,
  InteractionRecord,
  RedactedContent,
} from "./types";

// SYNTHETIC fixtures only: placeholder text, no personal data, key, token or card number.

class ResizeObserverStub {
  observe(): void {}
  unobserve(): void {}
  disconnect(): void {}
}

beforeAll(() => {
  vi.stubGlobal("ResizeObserver", ResizeObserverStub);
});
afterEach(cleanup);

const DOMAIN = "dom-1";
const ID = "1a1a1a1a-0000-4000-8000-000000000001";
const ID_FAILED = "1a1a1a1a-0000-4000-8000-000000000003";
const AGENT = "commercial:e2e:sandbox:agent:support-bot";
const PLACEHOLDER = "SYNTHETIC PROMPT PLACEHOLDER [[ns-redacted:email_address]]";

function record(id: string, over: Partial<InteractionRecord> = {}): InteractionRecord {
  return {
    schema_version: "1.0.0",
    interaction_id: id,
    cloud: "commercial",
    customer_id: "e2e",
    domain_id: DOMAIN,
    source_id: "src-e2e",
    event_id: "evt-1",
    correlation_id: "corr-1",
    capture_source: "edge_push",
    occurred_at: "2026-10-24T09:00:00Z",
    captured_at: "2026-10-24T09:00:01Z",
    agent_id: AGENT,
    principal_id: null,
    capture_policy_id: "support-capture",
    capture_policy_version: 2,
    detector_set_version: "ns-detectors-1",
    redaction_state: "redacted",
    parts: [{ part: "prompt", char_count: 60, truncated: false }],
    content_ref: {
      pointer: `content/${id}`,
      kek_uri: "https://ns-e2e-kv.vault.azure.net/keys/ns-content",
      algorithm: "aes_256_gcm",
      ciphertext_sha256: "0".repeat(64),
      byte_length: 512,
    },
    findings_summary: [{ category: "email_address", count: 2, action: "replaced" }],
    expires_at: "2026-11-23T09:00:01Z",
    ...over,
  };
}

const PAGE: InteractionPage = {
  items: [
    record(ID),
    record(ID_FAILED, {
      redaction_state: "redaction_failed",
      content_ref: null,
      findings_summary: [],
    }),
  ],
  continuation: null,
};

const CONTENT: RedactedContent = {
  schema_version: "1.0.0",
  interaction_id: ID,
  redaction_state: "redacted",
  detector_set_version: "ns-detectors-1",
  parts: [{ part: "prompt", text: PLACEHOLDER, truncated: false, findings: [] }],
};

const MANIFEST: InteractionExportManifest = {
  schema_version: "1.0.0",
  export_id: "3c3c3c3c-0000-4000-8000-000000000001",
  cloud: "commercial",
  customer_id: "e2e",
  domain_ids: [DOMAIN],
  requested_by: `commercial:e2e:entra:person:p-${"0".repeat(64)}`,
  requested_at: "2026-10-24T12:00:00Z",
  purpose: { purpose_code: "security_review", case_ref: null },
  filters: {
    from: "2026-10-01T00:00:00.000Z",
    to: "2026-10-02T00:00:00.000Z",
    agent_ids: [],
    detected_categories: [],
  },
  interaction_count: 2,
  interaction_ids: [ID, ID_FAILED],
  excluded_count: 3,
  includes_held_content: true,
  bundle: {
    pointer: "exports/x",
    kek_uri: "https://ns-e2e-kv.vault.azure.net/keys/ns-content",
    algorithm: "aes_256_gcm",
    ciphertext_sha256: "0".repeat(64),
    byte_length: 10,
  },
  audit_id: "2b2b2b2b-0000-4000-8000-000000000001",
  expires_at: "2026-10-25T12:00:00Z",
};

function problem(
  status: number,
  code: string,
  reason: string,
  headers: HeadersInit = {},
): Response {
  return new Response(
    JSON.stringify({
      schema_version: "1.0.0",
      type: "https://neurosphere.invalid/problems/x",
      title: code,
      status,
      code,
      reason,
      retryable: false,
      correlation_id: "corr-test",
    }),
    { status, headers: { "content-type": "application/problem+json", ...headers } },
  );
}

type Responder = (url: URL, init: RequestInit | undefined) => Response | undefined;

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status });
}

function setup(path: string, override?: Responder) {
  const fetchImpl = vi.fn<typeof fetch>((input, init) => {
    const url = new URL(String(input));
    const custom = override?.(url, init);
    if (custom !== undefined) return Promise.resolve(custom);
    const method = init?.method ?? "GET";
    if (url.pathname.endsWith("/content-reads")) return Promise.resolve(json(CONTENT));
    if (url.pathname.endsWith("/interaction-exports") && method === "POST") {
      return Promise.resolve(json(MANIFEST, 201));
    }
    if (url.pathname.endsWith("/bundle")) return Promise.resolve(json({ interactions: {} }));
    const detail = /\/interactions\/([0-9a-f-]{36})$/.exec(url.pathname);
    if (detail !== null) {
      const found = PAGE.items.find((r) => r.interaction_id === detail[1]);
      return Promise.resolve(found === undefined ? problem(404, "not_found", "x") : json(found));
    }
    return Promise.resolve(json(PAGE));
  });
  const client = createApiClient({
    baseUrl: "http://api.test",
    getToken: () => Promise.resolve("t"),
    fetchImpl,
    maxRetries: 0,
  });
  const router = createMemoryRouter(interactionsRoutes, { initialEntries: [path] });
  const view = render(
    <QueryProvider client={client}>
      <RouterProvider router={router} />
    </QueryProvider>,
  );
  return { fetchImpl, ...view };
}

const LIST = `/interactions?domain_id=${DOMAIN}`;
const OPEN = `${LIST}&interaction_id=${ID}`;

function calls(fetchImpl: ReturnType<typeof setup>["fetchImpl"], method = "GET") {
  return fetchImpl.mock.calls
    .filter((c) => (c[1]?.method ?? "GET") === method)
    .map((c) => ({ url: new URL(String(c[0])), body: c[1]?.body }));
}

async function openReveal(user: ReturnType<typeof userEvent.setup>) {
  await user.click(await screen.findByRole("button", { name: STRINGS.reveal.open }));
  return screen.findByRole("dialog", { hidden: true });
}

describe("interaction explorer list", () => {
  it("lists interactions in the domain path with redaction state and findings counts", async () => {
    const { fetchImpl } = setup(LIST);
    const rows = await screen.findAllByTestId("interaction-row");
    expect(rows).toHaveLength(2);
    expect(within(rows[0] as HTMLElement).getByText("2 findings")).toBeInTheDocument();
    expect(
      within(rows[1] as HTMLElement).getByText(STRINGS.redaction.redaction_failed),
    ).toBeInTheDocument();
    const [first] = calls(fetchImpl);
    expect(first?.url.pathname).toBe(`/api/v1/domains/${DOMAIN}/interactions`);
    expect(first?.url.searchParams.get("page_size")).toBe("25");
  });

  it("sends the applied filters as query parameters, times in UTC", async () => {
    const user = userEvent.setup();
    const { fetchImpl } = setup(LIST);
    await screen.findAllByTestId("interaction-row");
    await user.type(screen.getByLabelText(STRINGS.filters.agent), AGENT);
    await user.type(screen.getByLabelText(STRINGS.filters.tool), "commercial:e2e:sandbox:tool:t1");
    await user.selectOptions(screen.getByLabelText(STRINGS.filters.category), "email_address");
    const from = screen.getByLabelText(STRINGS.filters.from);
    await user.type(from, "2026-10-01T00:00");
    await user.click(screen.getByRole("button", { name: STRINGS.filters.apply }));
    await waitFor(() => expect(calls(fetchImpl).length).toBeGreaterThan(1));
    const last = calls(fetchImpl).at(-1)?.url;
    expect(last?.searchParams.get("agent_id")).toBe(AGENT);
    expect(last?.searchParams.get("tool_id")).toBe("commercial:e2e:sandbox:tool:t1");
    expect(last?.searchParams.get("detected_category")).toBe("email_address");
    expect(last?.searchParams.get("from")).toBe("2026-10-01T00:00:00Z");
    expect(last?.searchParams.has("principal_id")).toBe(false);
    expect(last?.searchParams.has("domain_id")).toBe(false);
  });

  it("refuses a malformed time filter without searching", async () => {
    const user = userEvent.setup();
    const { fetchImpl } = setup(LIST);
    await screen.findAllByTestId("interaction-row");
    await user.type(screen.getByLabelText(STRINGS.filters.to), "2026-02-31");
    await user.click(screen.getByRole("button", { name: STRINGS.filters.apply }));
    expect(screen.getByText(STRINGS.filters.timeInvalid)).toBeInTheDocument();
    expect(calls(fetchImpl)).toHaveLength(1);
    expect(toUtc("2026-10-01")).toBe("2026-10-01T00:00:00Z");
    expect(toUtc("01/10/2026")).toBeNull();
  });

  it("pages through the continuation token", async () => {
    const user = userEvent.setup();
    const { fetchImpl } = setup(LIST, (url) => {
      if (!url.pathname.endsWith("/interactions")) return undefined;
      return url.searchParams.get("continuation") === "next-1"
        ? json({ items: [record("1a1a1a1a-0000-4000-8000-000000000009")], continuation: null })
        : json({ items: [record(ID)], continuation: "next-1" });
    });
    await screen.findAllByTestId("interaction-row");
    await user.click(screen.getByRole("button", { name: STRINGS.loadMore }));
    await waitFor(() => expect(screen.getAllByTestId("interaction-row")).toHaveLength(2));
    expect(calls(fetchImpl).at(-1)?.url.searchParams.get("continuation")).toBe("next-1");
    expect(screen.queryByRole("button", { name: STRINGS.loadMore })).toBeNull();
  });

  it("shows the not-configured state when the explorer is off (503 reason in the body)", async () => {
    setup(LIST, () => problem(503, "dependency_transient", "interaction_explorer_unconfigured"));
    const state = await screen.findByTestId("explorer-unconfigured");
    expect(state).toHaveTextContent(STRINGS.errors.explorerUnconfiguredTitle);
    expect(screen.queryByTestId("error-state")).toBeNull();
  });

  it("shows the forbidden state for a domain without data.read", async () => {
    setup(LIST, () => problem(403, "forbidden", "permission_denied"));
    expect(await screen.findByTestId("forbidden-state")).toBeInTheDocument();
  });

  it("has no axe violations with the detail open", async () => {
    const { container } = setup(OPEN);
    await screen.findByTestId("interaction-detail");
    const results = await axe(container);
    expect(results.violations.map((v) => `${v.id}: ${v.help}`)).toEqual([]);
  });
});

describe("interaction detail", () => {
  it("shows findings, redaction state and the structured-identifiers coverage label", async () => {
    setup(OPEN);
    const detail = await screen.findByTestId("interaction-detail");
    expect(within(detail).getByTestId("coverage-label")).toHaveTextContent(
      "Detection coverage: structured identifiers only",
    );
    expect(within(detail).getByTestId("findings-list")).toHaveTextContent(
      "email_address: 2 (replaced)",
    );
    expect(within(detail).getByTestId("detail-redaction")).toHaveTextContent(
      STRINGS.redaction.redacted,
    );
    // Metadata only: no content is shown until a purpose is given.
    expect(screen.queryByText(PLACEHOLDER)).toBeNull();
  });

  it("disables reveal when nothing was stored", async () => {
    setup(`${LIST}&interaction_id=${ID_FAILED}`);
    await screen.findByTestId("interaction-detail");
    expect(screen.getByRole("button", { name: STRINGS.reveal.open })).toBeDisabled();
    expect(screen.getByTestId("no-content")).toHaveTextContent(STRINGS.detail.noContent);
  });
});

describe("reveal content", () => {
  it("requires a purpose, posts it, shows the content and discards it on close", async () => {
    const user = userEvent.setup();
    const { fetchImpl } = setup(OPEN);
    const dialog = await openReveal(user);
    await user.click(
      within(dialog).getByRole("button", { name: STRINGS.reveal.submit, hidden: true }),
    );
    expect(within(dialog).getByText(STRINGS.purpose.required)).toBeInTheDocument();
    expect(calls(fetchImpl, "POST")).toHaveLength(0);

    await user.selectOptions(
      within(dialog).getByTestId("reveal-purpose"),
      "incident_investigation",
    );
    await user.click(within(dialog).getByTestId("reveal-case-ref"));
    await user.paste("case-2026-0042");
    await user.click(
      within(dialog).getByRole("button", { name: STRINGS.reveal.submit, hidden: true }),
    );
    expect(await within(dialog).findByText(PLACEHOLDER)).toBeInTheDocument();
    const posts = calls(fetchImpl, "POST");
    expect(posts).toHaveLength(1);
    expect(posts[0]?.url.pathname).toBe(
      `/api/v1/domains/${DOMAIN}/interactions/${ID}/content-reads`,
    );
    expect(JSON.parse(String(posts[0]?.body))).toEqual({
      purpose_code: "incident_investigation",
      case_ref: "case-2026-0042",
    });
    // Focus moves to the revealed content.
    expect(document.activeElement).toHaveTextContent(STRINGS.reveal.contentHeading);

    await user.click(
      within(dialog).getByRole("button", { name: STRINGS.reveal.close, hidden: true }),
    );
    await waitFor(() => expect(screen.queryByText(PLACEHOLDER)).toBeNull());
    const again = await openReveal(user);
    expect(within(again).queryByText(PLACEHOLDER)).toBeNull();
    expect(within(again).getByTestId("reveal-purpose")).toHaveValue("");
  });

  it("refuses a GUID-shaped case reference before sending", async () => {
    const user = userEvent.setup();
    const { fetchImpl } = setup(OPEN);
    const dialog = await openReveal(user);
    await user.selectOptions(within(dialog).getByTestId("reveal-purpose"), "security_review");
    await user.click(within(dialog).getByTestId("reveal-case-ref"));
    await user.paste("0f0f0f0f-0000-4000-8000-000000000000");
    expect(within(dialog).getByText(STRINGS.purpose.caseRefGuid)).toBeInTheDocument();
    await user.click(
      within(dialog).getByRole("button", { name: STRINGS.reveal.submit, hidden: true }),
    );
    expect(calls(fetchImpl, "POST")).toHaveLength(0);
    expect(caseRefProblem("case 1")).toBe(STRINGS.purpose.caseRefInvalid);
    expect(caseRefProblem("")).toBeNull();
  });

  async function revealWith(response: Response) {
    const user = userEvent.setup();
    setup(OPEN, (url) => (url.pathname.endsWith("/content-reads") ? response : undefined));
    const dialog = await openReveal(user);
    await user.selectOptions(within(dialog).getByTestId("reveal-purpose"), "quality_review");
    await user.click(
      within(dialog).getByRole("button", { name: STRINGS.reveal.submit, hidden: true }),
    );
    return dialog;
  }

  it("explains the investigator role on 403", async () => {
    const dialog = await revealWith(problem(403, "forbidden", "permission_denied"));
    const alert = await within(dialog).findByTestId("reveal-forbidden");
    expect(alert).toHaveTextContent("interaction_investigator");
    expect(alert).toHaveTextContent("viewer assignment");
  });

  it("explains a refused purpose on 422", async () => {
    const dialog = await revealWith(problem(422, "invalid_schema", "interaction_purpose_invalid"));
    expect(await within(dialog).findByTestId("reveal-invalid")).toHaveTextContent(
      STRINGS.errors.purposeInvalid,
    );
  });

  it("says nothing was decrypted when the audit write fails (503)", async () => {
    const dialog = await revealWith(problem(503, "dependency_transient", "audit_write_failed"));
    expect(await within(dialog).findByTestId("reveal-unavailable")).toHaveTextContent(
      STRINGS.errors.auditUnavailable,
    );
  });

  it("names the unconfigured explorer on 503", async () => {
    const dialog = await revealWith(
      problem(503, "dependency_transient", "interaction_explorer_unconfigured"),
    );
    const alert = await within(dialog).findByTestId("reveal-unavailable");
    expect(alert).toHaveTextContent(STRINGS.errors.explorerUnconfiguredTitle);
    expect(alert).toHaveTextContent(STRINGS.errors.explorerUnconfigured);
  });
});

describe("export", () => {
  async function exportDialog() {
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: STRINGS.exportFlow.open }));
    const dialog = await screen.findByRole("dialog", { hidden: true });
    return { user, dialog };
  }

  async function fill(user: ReturnType<typeof userEvent.setup>, dialog: HTMLElement) {
    await user.selectOptions(within(dialog).getByTestId("export-purpose"), "security_review");
    await user.type(within(dialog).getByTestId("export-from"), "2026-10-01T00:00");
    await user.type(within(dialog).getByTestId("export-to"), "2026-10-02T00:00");
    await user.click(
      within(dialog).getByRole("button", { name: STRINGS.exportFlow.submit, hidden: true }),
    );
  }

  it("needs a purpose and a time range, then shows the manifest and downloads the bundle", async () => {
    const { fetchImpl } = setup(LIST);
    await screen.findAllByTestId("interaction-row");
    const { user, dialog } = await exportDialog();
    await user.click(
      within(dialog).getByRole("button", { name: STRINGS.exportFlow.submit, hidden: true }),
    );
    expect(within(dialog).getByText(STRINGS.purpose.required)).toBeInTheDocument();
    expect(within(dialog).getAllByText(STRINGS.exportFlow.rangeRequired).length).toBe(2);
    expect(calls(fetchImpl, "POST")).toHaveLength(0);

    await fill(user, dialog);
    const manifest = await within(dialog).findByTestId("export-manifest");
    expect(within(manifest).getByTestId("export-ids")).toHaveTextContent("2");
    expect(within(manifest).getByTestId("export-excluded")).toHaveTextContent("3");
    expect(within(manifest).getByTestId("export-held")).toHaveTextContent(STRINGS.exportFlow.yes);
    expect(within(manifest).getByTestId("export-audit-id")).toHaveTextContent(MANIFEST.audit_id);
    expect(within(manifest).getByTestId("export-expires")).toBeInTheDocument();
    const post = calls(fetchImpl, "POST")[0];
    expect(post?.url.pathname).toBe(`/api/v1/domains/${DOMAIN}/interaction-exports`);
    const sent = JSON.parse(String(post?.body)) as {
      purpose: unknown;
      filters: Record<string, unknown>;
    };
    expect(sent.purpose).toEqual({ purpose_code: "security_review", case_ref: null });
    expect(String(sent.filters["from"])).toMatch(/Z$/);
    expect(sent.filters["agent_ids"]).toEqual([]);

    const create = vi.fn(() => "blob:test");
    const revoke = vi.fn();
    URL.createObjectURL = create;
    URL.revokeObjectURL = revoke;
    await user.click(
      within(manifest).getByRole("button", { name: STRINGS.exportFlow.download, hidden: true }),
    );
    expect(await within(manifest).findByTestId("export-downloaded")).toBeInTheDocument();
    expect(create).toHaveBeenCalledTimes(1);
    expect(revoke).toHaveBeenCalledWith("blob:test");
    const bundle = calls(fetchImpl).find((c) => c.url.pathname.endsWith("/bundle"));
    expect(bundle?.url.pathname).toBe(
      `/api/v1/domains/${DOMAIN}/interaction-exports/${MANIFEST.export_id}/bundle`,
    );
  });

  it("explains the open-export limit with the Retry-After wait (429)", async () => {
    setup(LIST, (url, init) =>
      url.pathname.endsWith("/interaction-exports") && init?.method === "POST"
        ? problem(429, "rate_limited", "interaction_export_limit_reached", {
            "Retry-After": "7200",
          })
        : undefined,
    );
    await screen.findAllByTestId("interaction-row");
    const { user, dialog } = await exportDialog();
    await fill(user, dialog);
    const alert = await within(dialog).findByTestId("export-limit");
    expect(alert).toHaveTextContent(STRINGS.errors.limitTitle);
    expect(alert).toHaveTextContent("in about 2 hours");
  });

  it("explains an empty selection (404)", async () => {
    setup(LIST, (url, init) =>
      url.pathname.endsWith("/interaction-exports") && init?.method === "POST"
        ? problem(404, "not_found", "interaction_export_empty")
        : undefined,
    );
    await screen.findAllByTestId("interaction-row");
    const { user, dialog } = await exportDialog();
    await fill(user, dialog);
    expect(await within(dialog).findByTestId("export-not_found")).toHaveTextContent(
      STRINGS.errors.exportEmpty,
    );
  });
});
