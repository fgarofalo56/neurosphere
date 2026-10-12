import {
  CORRELATION_HEADER,
  DependencyTransientError,
  ScopeParameterError,
  UnexpectedResponseError,
  errorFromResponse,
  isApiError,
} from "./errors.js";
import type { QueryParams } from "./pagination.js";

export type HttpMethod = "GET" | "POST" | "PUT" | "PATCH" | "DELETE";

export interface ApiClientOptions {
  baseUrl: string;
  /** The auth lane's token seam, injected. The client never imports src/auth. */
  getToken: () => Promise<string>;
  fetchImpl?: typeof fetch;
  /** Automatic retries for retryable 429/5xx on idempotent methods. Default 2. */
  maxRetries?: number;
  /** Upper bound on any single retry wait, seconds. Default 30. */
  maxRetryWaitSeconds?: number;
  sleep?: (ms: number) => Promise<void>;
  newCorrelationId?: () => string;
}

export interface RequestOptions {
  method?: HttpMethod;
  path: string;
  query?: QueryParams;
  body?: unknown;
  /** Sent as If-Match for optimistic concurrency (stale_version on mismatch). */
  ifMatch?: string;
  signal?: AbortSignal;
}

export interface ApiClient {
  request<T>(options: RequestOptions): Promise<T>;
  get<T>(path: string, query?: QueryParams, signal?: AbortSignal): Promise<T>;
  post<T>(path: string, body?: unknown, signal?: AbortSignal): Promise<T>;
  put<T>(path: string, body?: unknown, ifMatch?: string, signal?: AbortSignal): Promise<T>;
  patch<T>(path: string, body?: unknown, ifMatch?: string, signal?: AbortSignal): Promise<T>;
  delete<T>(path: string, signal?: AbortSignal): Promise<T>;
}

/** The server derives scope; the client must never send these. */
const FORBIDDEN_SCOPE_KEYS = new Set(["domain_id", "customer_id"]);

function assertNoScopeKeys(value: unknown, depth = 0): void {
  if (depth > 20 || typeof value !== "object" || value === null) return;
  if (Array.isArray(value)) {
    for (const item of value) assertNoScopeKeys(item, depth + 1);
    return;
  }
  for (const [key, child] of Object.entries(value)) {
    if (FORBIDDEN_SCOPE_KEYS.has(key)) throw new ScopeParameterError(key);
    assertNoScopeKeys(child, depth + 1);
  }
}

function buildUrl(baseUrl: string, path: string, query: QueryParams | undefined): string {
  const base = baseUrl.replace(/\/+$/, "");
  const rel = path.startsWith("/") ? path : `/${path}`;
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(query ?? {})) {
    if (FORBIDDEN_SCOPE_KEYS.has(key)) throw new ScopeParameterError(key);
    if (value !== undefined) search.append(key, String(value));
  }
  const qs = search.toString();
  return qs === "" ? `${base}${rel}` : `${base}${rel}?${qs}`;
}

async function readBody(response: Response): Promise<unknown> {
  const text = await response.text();
  if (text === "") return undefined;
  try {
    return JSON.parse(text) as unknown;
  } catch {
    return undefined;
  }
}

const defaultSleep = (ms: number): Promise<void> => new Promise((r) => setTimeout(r, ms));

export function createApiClient(options: ApiClientOptions): ApiClient {
  const fetchImpl = options.fetchImpl ?? ((...args: Parameters<typeof fetch>) => fetch(...args));
  const maxRetries = options.maxRetries ?? 2;
  const maxWaitMs = (options.maxRetryWaitSeconds ?? 30) * 1000;
  const sleep = options.sleep ?? defaultSleep;
  const newId = options.newCorrelationId ?? (() => crypto.randomUUID());

  async function request<T>(req: RequestOptions): Promise<T> {
    const method = req.method ?? "GET";
    const url = buildUrl(options.baseUrl, req.path, req.query);
    assertNoScopeKeys(req.body);
    // One correlation id per logical request, propagated unchanged across retries.
    const correlationId = newId();
    const idempotent = method === "GET" || method === "PUT" || method === "DELETE";

    for (let attempt = 0; ; attempt++) {
      const token = await options.getToken();
      const headers: Record<string, string> = {
        Accept: "application/json, application/problem+json",
        Authorization: `Bearer ${token}`,
        [CORRELATION_HEADER]: correlationId,
      };
      if (req.ifMatch !== undefined) headers["If-Match"] = req.ifMatch;
      const init: RequestInit = { method, headers };
      if (req.body !== undefined) {
        headers["Content-Type"] = "application/json";
        init.body = JSON.stringify(req.body);
      }
      if (req.signal !== undefined) init.signal = req.signal;

      let error: unknown;
      try {
        const response = await fetchImpl(url, init);
        const body = await readBody(response);
        if (response.ok) {
          if (response.status === 204) return undefined as T;
          if (body === undefined) {
            throw new UnexpectedResponseError({
              status: response.status,
              retryable: false,
              correlationId,
              message: "Response body was empty or not valid JSON",
            });
          }
          return body as T;
        }
        error = errorFromResponse({
          status: response.status,
          body,
          retryAfterHeader: response.headers.get("Retry-After"),
          correlationId: response.headers.get(CORRELATION_HEADER) ?? correlationId,
        });
      } catch (caught) {
        if (isApiError(caught)) {
          error = caught;
        } else if (req.signal?.aborted === true) {
          throw caught;
        } else {
          error = new DependencyTransientError({
            status: 0,
            retryable: true,
            correlationId,
            message: "Network failure",
          });
        }
      }

      if (!isApiError(error)) throw error;
      // Only 429 and transient dependency failures retry; 401/403/409/422 never do.
      const retriable =
        (error.code === "rate_limited" || error.code === "dependency_transient") &&
        error.retryable &&
        (idempotent || error.code === "rate_limited") &&
        attempt < maxRetries;
      if (!retriable) throw error;
      const waitMs = Math.min(
        error.retryAfterSeconds !== undefined ? error.retryAfterSeconds * 1000 : 250 * 2 ** attempt,
        maxWaitMs,
      );
      await sleep(waitMs);
    }
  }

  return {
    request,
    get: (path, query, signal) =>
      request({ method: "GET", path, ...(query && { query }), ...(signal && { signal }) }),
    post: (path, body, signal) =>
      request({ method: "POST", path, body, ...(signal && { signal }) }),
    put: (path, body, ifMatch, signal) =>
      request({
        method: "PUT",
        path,
        body,
        ...(ifMatch && { ifMatch }),
        ...(signal && { signal }),
      }),
    patch: (path, body, ifMatch, signal) =>
      request({
        method: "PATCH",
        path,
        body,
        ...(ifMatch && { ifMatch }),
        ...(signal && { signal }),
      }),
    delete: (path, signal) => request({ method: "DELETE", path, ...(signal && { signal }) }),
  };
}
