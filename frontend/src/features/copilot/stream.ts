import {
  CORRELATION_HEADER,
  DependencyTransientError,
  UnexpectedResponseError,
  errorFromResponse,
  isApiError,
} from "../../api/errors.js";
import { COPILOT_CONVERSATIONS_PATH, conversationMessagesPath } from "./paths";
import type {
  ActionSuggestionEvent,
  ChartPlan,
  CitationEvent,
  ContextEcho,
  CopilotEvent,
  ConversationCreated,
  FilterValue,
  MessageBody,
  TerminalReason,
  ToolEvent,
} from "./types";

/**
 * How the stream client reaches the API. The auth lane's token seam is injected, exactly like
 * `createApiClient`: this module never imports `src/auth`.
 */
export interface StreamTransport {
  readonly baseUrl: string;
  readonly getToken: () => Promise<string>;
  readonly fetchImpl?: typeof fetch;
  readonly newCorrelationId?: () => string;
}

// ---- SSE framing -----------------------------------------------------------------------------

export interface RawSseEvent {
  readonly event: string;
  readonly data: string;
}

/**
 * Incremental `text/event-stream` parser. Feed it decoded text in arbitrary chunks; it returns
 * the events completed by each chunk. Comment lines and unknown fields are ignored, multi-line
 * `data:` is joined with newlines, CRLF and LF are both accepted.
 */
export class SseParser {
  private buffer = "";

  push(chunk: string): RawSseEvent[] {
    this.buffer += chunk.replace(/\r\n?/g, "\n");
    const events: RawSseEvent[] = [];
    for (;;) {
      const end = this.buffer.indexOf("\n\n");
      if (end === -1) break;
      const block = this.buffer.slice(0, end);
      this.buffer = this.buffer.slice(end + 2);
      const parsed = parseBlock(block);
      if (parsed !== null) events.push(parsed);
    }
    return events;
  }
}

function parseBlock(block: string): RawSseEvent | null {
  let event = "message";
  const data: string[] = [];
  for (const line of block.split("\n")) {
    if (line === "" || line.startsWith(":")) continue;
    const colon = line.indexOf(":");
    const field = colon === -1 ? line : line.slice(0, colon);
    let value = colon === -1 ? "" : line.slice(colon + 1);
    if (value.startsWith(" ")) value = value.slice(1);
    if (field === "event") event = value;
    else if (field === "data") data.push(value);
  }
  return data.length === 0 ? null : { event, data: data.join("\n") };
}

// ---- typed events ----------------------------------------------------------------------------

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isStringOrNull(value: unknown): value is string | null {
  return value === null || typeof value === "string";
}

function isStringArray(value: unknown): value is string[] {
  return Array.isArray(value) && value.every((v) => typeof v === "string");
}

function isFilters(value: unknown): value is Record<string, FilterValue> {
  return (
    isRecord(value) && Object.values(value).every((v) => typeof v === "string" || isStringArray(v))
  );
}

function asContext(d: Record<string, unknown>): ContextEcho | null {
  const raw = d["time_range"];
  let range: { from: string; to: string } | null = null;
  if (raw !== null && raw !== undefined) {
    if (!isRecord(raw) || typeof raw["from"] !== "string" || typeof raw["to"] !== "string") {
      return null;
    }
    range = { from: raw["from"], to: raw["to"] };
  }
  if (
    !isStringOrNull(d["page"]) ||
    !isStringOrNull(d["route"]) ||
    !isFilters(d["filters"]) ||
    !isStringArray(d["selection"]) ||
    typeof d["dropped_selection_count"] !== "number" ||
    !isStringArray(d["applied_domains"])
  ) {
    return null;
  }
  return {
    page: d["page"],
    route: d["route"],
    filters: d["filters"],
    time_range: range,
    selection: d["selection"],
    dropped_selection_count: d["dropped_selection_count"],
    applied_domains: d["applied_domains"],
  };
}

function asTool(d: Record<string, unknown>): ToolEvent | null {
  const status = d["status"];
  if (typeof d["name"] !== "string") return null;
  if (status !== "started" && status !== "ok" && status !== "refused") return null;
  return { name: d["name"], status };
}

function asCitation(d: Record<string, unknown>): CitationEvent | null {
  const freshness = d["freshness"];
  if (
    typeof d["record_id"] !== "string" ||
    typeof d["kind"] !== "string" ||
    typeof d["source"] !== "string" ||
    !isStringOrNull(d["as_of"]) ||
    (freshness !== "fresh" && freshness !== "stale" && freshness !== "unknown")
  ) {
    return null;
  }
  return {
    record_id: d["record_id"],
    kind: d["kind"],
    source: d["source"],
    as_of: d["as_of"],
    freshness,
  };
}

function asChart(d: Record<string, unknown>): ChartPlan | null {
  const plan = d["chart_plan"];
  // Shape check only; ChartFrame re-validates the spec and the server already did.
  if (!isRecord(plan) || !isRecord(plan["spec"]) || !Array.isArray(plan["citations"])) return null;
  return plan as unknown as ChartPlan;
}

function asSuggestion(d: Record<string, unknown>): ActionSuggestionEvent | null {
  if (
    typeof d["intent_id"] !== "string" ||
    typeof d["domain_id"] !== "string" ||
    typeof d["action_type"] !== "string" ||
    !isRecord(d["target"]) ||
    typeof d["intent_hash"] !== "string"
  ) {
    return null;
  }
  return {
    intent_id: d["intent_id"],
    domain_id: d["domain_id"],
    action_type: d["action_type"],
    target: d["target"],
    intent_hash: d["intent_hash"],
  };
}

function asReason(d: Record<string, unknown>): TerminalReason | null {
  if (
    typeof d["message_id"] !== "string" ||
    typeof d["reason_code"] !== "string" ||
    typeof d["reason"] !== "string"
  ) {
    return null;
  }
  return { message_id: d["message_id"], reason_code: d["reason_code"], reason: d["reason"] };
}

/** Terminal names; exactly one ends every turn. */
const TERMINALS: ReadonlySet<string> = new Set(["done", "abstain", "denied", "error"]);

export function isTerminal(event: CopilotEvent): boolean {
  return TERMINALS.has(event.name);
}

/**
 * Parses one raw event into a typed one. Unknown event names return `null` (ignored, so the
 * server can add events additively). A KNOWN terminal event with a malformed payload becomes an
 * `error` event rather than being dropped, so a turn can never hang open on a bad terminal.
 */
export function parseEvent(raw: RawSseEvent): CopilotEvent | null {
  let payload: unknown;
  try {
    payload = JSON.parse(raw.data);
  } catch {
    return TERMINALS.has(raw.event) ? malformedTerminal() : null;
  }
  if (!isRecord(payload)) return TERMINALS.has(raw.event) ? malformedTerminal() : null;
  switch (raw.event) {
    case "context": {
      const data = asContext(payload);
      return data === null ? null : { name: "context", data };
    }
    case "tool": {
      const data = asTool(payload);
      return data === null ? null : { name: "tool", data };
    }
    case "token":
      return typeof payload["text"] === "string"
        ? { name: "token", data: { text: payload["text"] } }
        : null;
    case "citation": {
      const data = asCitation(payload);
      return data === null ? null : { name: "citation", data };
    }
    case "chart": {
      const chart = asChart(payload);
      return chart === null ? null : { name: "chart", data: { chart_plan: chart } };
    }
    case "action_suggestion": {
      const data = asSuggestion(payload);
      return data === null ? null : { name: "action_suggestion", data };
    }
    case "done":
      return typeof payload["message_id"] === "string"
        ? { name: "done", data: { message_id: payload["message_id"], status: "answered" } }
        : malformedTerminal();
    case "abstain": {
      const data = asReason(payload);
      return data === null ? malformedTerminal() : { name: "abstain", data };
    }
    case "denied": {
      const data = asReason(payload);
      return data === null ? malformedTerminal() : { name: "denied", data };
    }
    case "error":
      return typeof payload["code"] === "string" && typeof payload["detail"] === "string"
        ? { name: "error", data: { code: payload["code"], detail: payload["detail"] } }
        : malformedTerminal();
    default:
      return null;
  }
}

function malformedTerminal(): CopilotEvent {
  return {
    name: "error",
    data: { code: "unexpected_response", detail: "The assistant sent an unreadable final event." },
  };
}

// ---- HTTP ------------------------------------------------------------------------------------

function url(transport: StreamTransport, path: string): string {
  const base = transport.baseUrl.replace(/\/+$/, "");
  return `${base}${path}`;
}

async function failure(response: Response, correlationId: string): Promise<never> {
  let body: unknown;
  try {
    body = JSON.parse(await response.text());
  } catch {
    body = undefined;
  }
  throw errorFromResponse({
    status: response.status,
    body,
    retryAfterHeader: response.headers.get("Retry-After"),
    correlationId: response.headers.get(CORRELATION_HEADER) ?? correlationId,
  });
}

async function send(
  transport: StreamTransport,
  path: string,
  accept: string,
  body: unknown,
  signal: AbortSignal | undefined,
): Promise<{ response: Response; correlationId: string }> {
  const fetchImpl = transport.fetchImpl ?? ((...args: Parameters<typeof fetch>) => fetch(...args));
  const correlationId = (transport.newCorrelationId ?? (() => crypto.randomUUID()))();
  const token = await transport.getToken();
  const headers: Record<string, string> = {
    Accept: accept,
    Authorization: `Bearer ${token}`,
    [CORRELATION_HEADER]: correlationId,
  };
  const init: RequestInit = { method: "POST", headers };
  if (body !== undefined) {
    headers["Content-Type"] = "application/json";
    init.body = JSON.stringify(body);
  }
  if (signal !== undefined) init.signal = signal;
  try {
    return { response: await fetchImpl(url(transport, path), init), correlationId };
  } catch (caught) {
    if (isApiError(caught) || signal?.aborted === true) throw caught;
    throw new DependencyTransientError({
      status: 0,
      retryable: true,
      correlationId,
      message: "Network failure",
    });
  }
}

/** `POST /api/v1/copilot/conversations`. HTTP failures throw typed `ApiError`s. */
export async function createConversation(
  transport: StreamTransport,
  signal?: AbortSignal,
): Promise<ConversationCreated> {
  const { response, correlationId } = await send(
    transport,
    COPILOT_CONVERSATIONS_PATH,
    "application/json, application/problem+json",
    undefined,
    signal,
  );
  if (!response.ok) return failure(response, correlationId);
  const body: unknown = await response.json().catch(() => undefined);
  if (!isRecord(body) || typeof body["id"] !== "string") {
    throw new UnexpectedResponseError({
      status: response.status,
      retryable: false,
      correlationId,
      message: "Conversation response was not understood",
    });
  }
  return body as unknown as ConversationCreated;
}

/**
 * `POST .../conversations/{id}/messages`, yielding typed events as they arrive. This is a POST
 * with a bearer token, so it uses `fetch` and a streaming reader, not `EventSource`.
 *
 * HTTP failures (403 no `data.read`, 404, 422, 503 fail-closed) throw typed `ApiError`s before
 * the first event. Aborting the signal ends the generator by throwing the abort error. A stream
 * that ends without a terminal event yields a synthetic `error` so the UI never waits forever.
 */
export async function* streamMessage(
  transport: StreamTransport,
  conversationId: string,
  body: MessageBody,
  signal?: AbortSignal,
): AsyncGenerator<CopilotEvent, void, undefined> {
  const { response, correlationId } = await send(
    transport,
    conversationMessagesPath(conversationId),
    "text/event-stream, application/problem+json",
    body,
    signal,
  );
  if (!response.ok) return failure(response, correlationId);
  if (response.body === null) {
    throw new UnexpectedResponseError({
      status: response.status,
      retryable: false,
      correlationId,
      message: "The response had no body to stream",
    });
  }
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  const parser = new SseParser();
  let ended = false;
  try {
    for (;;) {
      const { done, value } = await reader.read();
      const text = done ? decoder.decode() : decoder.decode(value, { stream: true });
      for (const raw of parser.push(done ? `${text}\n\n` : text)) {
        const event = parseEvent(raw);
        if (event === null) continue;
        yield event;
        if (isTerminal(event)) {
          ended = true;
          return;
        }
      }
      if (done) break;
    }
  } finally {
    // Release the connection on early return, abort or error.
    void reader.cancel().catch(() => undefined);
  }
  if (!ended) {
    yield {
      name: "error",
      data: { code: "dependency_transient", detail: "The assistant stream ended unexpectedly." },
    };
  }
}
