/**
 * Tiny Node mock API for Playwright (C10). No network beyond loopback, no
 * credentials: the "token" is an obviously fake string minted by the e2e MSAL
 * stub (tests/e2e-support/stubMsal.ts).
 *
 * It only imitates the authorization *outcome* the real API (PRP-06) owns: a
 * persona workspace answers 200 when the caller's fake token carries the
 * matching role and a 403 ProblemDetails otherwise. The UI never decides.
 *
 * Run directly with Node 24 (native type stripping): node tests/mock-api/server.ts
 */
import { createServer, type IncomingMessage, type Server, type ServerResponse } from "node:http";
import { fileURLToPath } from "node:url";
import type { ProblemDetails } from "@neurosphere/contracts";

export const DEFAULT_PORT = 4010;
export const FAKE_TOKEN_PREFIX = "ns-e2e-fake-token.";
const PERSONAS = ["viewer", "analyst", "steward", "admin", "auditor"] as const;
const WORKSPACE_PATH = /^\/api\/v1\/workspaces\/([^/]+)\/?$/;

export interface MockApiOptions {
  /** Origin of the web app under test; echoed back for CORS. */
  readonly allowedOrigin: string;
  /** Base URL the mock tells the app to use (config.json apiBaseUrl). */
  readonly apiBaseUrl: string;
}

function problem(correlationId: string, instance: string): ProblemDetails {
  return {
    schema_version: "1.0.0",
    type: "https://neurosphere.invalid/problems/forbidden",
    title: "Forbidden",
    status: 403,
    detail: "The caller is not permitted to use this workspace.",
    instance,
    code: "forbidden",
    retryable: false,
    correlation_id: correlationId,
  };
}

/** Role carried by the fake token ("ns-e2e-fake-token.Viewer"), lower-cased, or undefined. */
export function roleFromAuthorization(header: string | undefined): string | undefined {
  if (header === undefined || !header.startsWith("Bearer ")) return undefined;
  const token = header.slice("Bearer ".length).trim();
  if (!token.startsWith(FAKE_TOKEN_PREFIX)) return undefined;
  const role = token.slice(FAKE_TOKEN_PREFIX.length).toLowerCase();
  return role === "" ? undefined : role;
}

/** The runtime config.json the e2e app must receive (apiBaseUrl points at this server). */
export function mockPublicConfig(apiBaseUrl: string): Record<string, string> {
  return {
    cloud: "commercial",
    tenantId: "00000000-0000-0000-0000-000000000000",
    clientId: "00000000-0000-0000-0000-000000000000",
    apiBaseUrl,
    apiScope: "api://neurosphere-e2e/access_as_user",
  };
}

function send(
  res: ServerResponse,
  status: number,
  body: unknown,
  headers: Record<string, string>,
  contentType = "application/json",
): void {
  res.writeHead(status, { "content-type": contentType, ...headers });
  res.end(JSON.stringify(body));
}

export function createMockApi(options: MockApiOptions): Server {
  return createServer((req: IncomingMessage, res: ServerResponse) => {
    const correlationId = `e2e-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`;
    const cors: Record<string, string> = {
      "access-control-allow-origin": options.allowedOrigin,
      "access-control-allow-headers": "authorization, content-type, x-correlation-id, if-match",
      "access-control-allow-methods": "GET, OPTIONS",
      "access-control-expose-headers": "x-correlation-id, retry-after",
      vary: "Origin",
      "x-correlation-id": correlationId,
    };
    const url = new URL(req.url ?? "/", "http://mock.invalid");

    if (req.method === "OPTIONS") {
      res.writeHead(204, cors);
      res.end();
      return;
    }
    if (req.method !== "GET") {
      send(res, 405, { error: "method not allowed" }, cors);
      return;
    }
    if (url.pathname === "/api/v1/health") {
      send(res, 200, { status: "ok" }, cors);
      return;
    }
    if (url.pathname === "/config.json") {
      send(res, 200, mockPublicConfig(options.apiBaseUrl), cors);
      return;
    }
    const match = WORKSPACE_PATH.exec(url.pathname);
    if (match !== null) {
      const persona = (match[1] ?? "").toLowerCase();
      if (!(PERSONAS as readonly string[]).includes(persona)) {
        send(res, 404, { error: "unknown workspace" }, cors);
        return;
      }
      const role = roleFromAuthorization(req.headers.authorization);
      if (role === undefined) {
        send(res, 401, { error: "missing or unrecognised token" }, cors);
        return;
      }
      if (role !== persona) {
        send(res, 403, problem(correlationId, url.pathname), cors, "application/problem+json");
        return;
      }
      send(res, 200, { workspace: persona, items: [] }, cors);
      return;
    }
    send(res, 404, { error: "not found" }, cors);
  });
}

const isMain = process.argv[1] !== undefined && fileURLToPath(import.meta.url) === process.argv[1];
if (isMain) {
  const port = Number(process.env["NS_MOCK_API_PORT"] ?? DEFAULT_PORT);
  const appOrigin = process.env["NS_E2E_APP_ORIGIN"] ?? "http://127.0.0.1:4173";
  const server = createMockApi({
    allowedOrigin: appOrigin,
    apiBaseUrl: `http://127.0.0.1:${port}`,
  });
  server.listen(port, "127.0.0.1", () => {
    console.log(`mock api listening on http://127.0.0.1:${port}`);
  });
}
