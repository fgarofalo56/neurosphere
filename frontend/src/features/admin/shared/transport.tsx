import {
  useMutation,
  useQuery,
  type UseMutationResult,
  type UseQueryResult,
} from "@tanstack/react-query";
import { createContext, useContext, useMemo, type ReactElement, type ReactNode } from "react";
import {
  CORRELATION_HEADER,
  DependencyTransientError,
  UnexpectedResponseError,
  errorFromResponse,
  type ApiError,
} from "../../../api/index.js";
import { ConfigContext } from "../../../app/ConfigContext";
import { getToken } from "../../../auth/token";

/**
 * Transport for the admin console. The shared `ApiClient` returns only the response body, but the
 * PRP-39 identity routes hand back the document ETag as a header and the audit export is a file,
 * so the admin pages make these requests through this seam. It keeps the client's contract: a
 * bearer token, one correlation id per request, typed errors from `errorFromResponse`, and no
 * retry of a failed write. The server derives scope; nothing here decides access.
 */
export interface AdminTransport {
  readonly baseUrl: string;
  readonly getToken: () => Promise<string>;
  readonly fetchImpl?: typeof fetch;
  readonly newCorrelationId?: () => string;
}

const TransportContext = createContext<AdminTransport | null>(null);

/** Test seam (and escape hatch): supply the transport instead of deriving it from app config. */
export function AdminTransportProvider({
  transport,
  children,
}: {
  readonly transport: AdminTransport;
  readonly children: ReactNode;
}): ReactElement {
  return <TransportContext.Provider value={transport}>{children}</TransportContext.Provider>;
}

export function useAdminTransport(): AdminTransport {
  const explicit = useContext(TransportContext);
  const config = useContext(ConfigContext);
  const baseUrl = config?.apiBaseUrl;
  return useMemo(() => {
    if (explicit !== null) return explicit;
    if (baseUrl === undefined) {
      throw new Error("The admin console needs an AdminTransportProvider or the app config");
    }
    return { baseUrl, getToken };
  }, [explicit, baseUrl]);
}

export type AdminMethod = "GET" | "POST" | "PUT" | "DELETE";

export interface AdminRequest {
  readonly method?: AdminMethod;
  readonly path: string;
  readonly query?: Readonly<Record<string, string | number | boolean | undefined>>;
  readonly body?: unknown;
  /** Sent verbatim as If-Match. Omitted for the first entry of a new principal. */
  readonly ifMatch?: string | undefined;
  readonly signal?: AbortSignal;
}

export interface AdminResponse<T> {
  readonly data: T;
  /** The ETag response header, verbatim (quotes included), or undefined. */
  readonly etag: string | undefined;
}

function buildUrl(transport: AdminTransport, req: AdminRequest): string {
  const base = transport.baseUrl.replace(/\/+$/, "");
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(req.query ?? {})) {
    if (value !== undefined) search.append(key, String(value));
  }
  const qs = search.toString();
  return `${base}${req.path}${qs === "" ? "" : `?${qs}`}`;
}

async function send(
  transport: AdminTransport,
  req: AdminRequest,
  accept: string,
): Promise<{ response: Response; correlationId: string }> {
  const fetchImpl = transport.fetchImpl ?? ((...args: Parameters<typeof fetch>) => fetch(...args));
  const correlationId = (transport.newCorrelationId ?? (() => crypto.randomUUID()))();
  const token = await transport.getToken();
  const headers: Record<string, string> = {
    Accept: accept,
    Authorization: `Bearer ${token}`,
    [CORRELATION_HEADER]: correlationId,
  };
  if (req.ifMatch !== undefined) headers["If-Match"] = req.ifMatch;
  const init: RequestInit = { method: req.method ?? "GET", headers };
  if (req.body !== undefined) {
    headers["Content-Type"] = "application/json";
    init.body = JSON.stringify(req.body);
  }
  if (req.signal !== undefined) init.signal = req.signal;
  try {
    return { response: await fetchImpl(buildUrl(transport, req), init), correlationId };
  } catch (caught) {
    if (req.signal?.aborted === true) throw caught;
    throw new DependencyTransientError({
      status: 0,
      retryable: true,
      correlationId,
      message: "Network failure",
    });
  }
}

function parseJson(text: string): unknown {
  if (text === "") return undefined;
  try {
    return JSON.parse(text) as unknown;
  } catch {
    return undefined;
  }
}

async function failure(response: Response, correlationId: string): Promise<ApiError> {
  return errorFromResponse({
    status: response.status,
    body: parseJson(await response.text()),
    retryAfterHeader: response.headers.get("Retry-After"),
    correlationId: response.headers.get(CORRELATION_HEADER) ?? correlationId,
  });
}

export async function adminRequest<T>(
  transport: AdminTransport,
  req: AdminRequest,
): Promise<AdminResponse<T>> {
  const { response, correlationId } = await send(
    transport,
    req,
    "application/json, application/problem+json",
  );
  if (!response.ok) throw await failure(response, correlationId);
  const data = parseJson(await response.text());
  if (data === undefined) {
    throw new UnexpectedResponseError({
      status: response.status,
      retryable: false,
      correlationId,
      message: "Response body was empty or not valid JSON",
    });
  }
  return { data: data as T, etag: response.headers.get("ETag") ?? undefined };
}

export interface AdminDownload {
  readonly blob: Blob;
  readonly filename: string;
  /** Rows the server says it exported, or undefined when it did not say. */
  readonly rows: number | undefined;
  readonly truncated: boolean;
}

/** A file download through the bearer-token path: the URL never carries a token. */
export async function adminDownload(
  transport: AdminTransport,
  req: AdminRequest,
  fallbackName: string,
): Promise<AdminDownload> {
  const { response, correlationId } = await send(transport, req, "*/*, application/problem+json");
  if (!response.ok) throw await failure(response, correlationId);
  const blob = await response.blob();
  const disposition = response.headers.get("Content-Disposition") ?? "";
  // Only a plain file name is accepted from the header; anything else uses the fallback.
  const named = /filename="?([A-Za-z0-9._-]{1,100})"?/.exec(disposition)?.[1];
  const rowsHeader = response.headers.get("X-NeuroSphere-Export-Rows");
  const rows = rowsHeader === null ? undefined : Number(rowsHeader);
  return {
    blob,
    filename: named ?? fallbackName,
    rows: rows !== undefined && Number.isFinite(rows) ? rows : undefined,
    truncated: response.headers.get("X-NeuroSphere-Export-Truncated") === "true",
  };
}

/** A GET that keeps the ETag. `key` names the cache entry; `params` distinguish requests. */
export function useAdminGet<T>(
  key: string,
  req: AdminRequest,
  enabled = true,
): UseQueryResult<AdminResponse<T>, ApiError> {
  const transport = useAdminTransport();
  return useQuery<AdminResponse<T>, ApiError>({
    queryKey: [key, req.path, req.query ?? {}],
    queryFn: ({ signal }) => adminRequest<T>(transport, { ...req, signal }),
    enabled,
  });
}

/**
 * A write with `If-Match`. `build` turns the variables into the request, so the ETag the user
 * confirmed is the one sent. A 409 surfaces as `StaleVersionError`; it is never retried.
 */
export function useEtagMutation<TVars, TData>(
  build: (vars: TVars) => AdminRequest,
): UseMutationResult<AdminResponse<TData>, ApiError, TVars> {
  const transport = useAdminTransport();
  return useMutation<AdminResponse<TData>, ApiError, TVars>({
    mutationFn: (vars) => adminRequest<TData>(transport, build(vars)),
  });
}
