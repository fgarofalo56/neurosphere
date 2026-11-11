import {
  createContext,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactElement,
  type ReactNode,
} from "react";
import { CORRELATION_HEADER, errorFromResponse } from "../../api/errors.js";
import { ConfigContext } from "../../app/ConfigContext";
import { getToken } from "../../auth/token";
import { COPILOT_STATUS_PATH } from "./paths";
import type { StreamTransport } from "./stream";
import type { CopilotStatus } from "./types";

const TransportContext = createContext<StreamTransport | null>(null);

export interface CopilotTransportProviderProps {
  readonly transport: StreamTransport;
  readonly children: ReactNode;
}

/** Test seam (and escape hatch): supply the transport instead of deriving it from app config. */
export function CopilotTransportProvider({
  transport,
  children,
}: CopilotTransportProviderProps): ReactElement {
  return <TransportContext.Provider value={transport}>{children}</TransportContext.Provider>;
}

/**
 * The transport for the stream client: an explicit provider wins; otherwise the app's runtime
 * config supplies the API base URL and the auth lane's token seam supplies the bearer token.
 * `null` when neither exists (the dock then reports the assistant as unavailable).
 */
export function useCopilotTransport(): StreamTransport | null {
  const explicit = useContext(TransportContext);
  const config = useContext(ConfigContext);
  const baseUrl = config?.apiBaseUrl;
  return useMemo(() => {
    if (explicit !== null) return explicit;
    return baseUrl === undefined ? null : { baseUrl, getToken };
  }, [explicit, baseUrl]);
}

/** `GET /api/v1/copilot/status`. HTTP failures (401, 5xx) throw typed `ApiError`s. */
export async function fetchCopilotStatus(
  transport: StreamTransport,
  signal?: AbortSignal,
): Promise<CopilotStatus> {
  const fetchImpl = transport.fetchImpl ?? ((...args: Parameters<typeof fetch>) => fetch(...args));
  const correlationId = (transport.newCorrelationId ?? (() => crypto.randomUUID()))();
  const token = await transport.getToken();
  const init: RequestInit = {
    method: "GET",
    headers: {
      Accept: "application/json, application/problem+json",
      Authorization: `Bearer ${token}`,
      [CORRELATION_HEADER]: correlationId,
    },
  };
  if (signal !== undefined) init.signal = signal;
  const base = transport.baseUrl.replace(/\/+$/, "");
  const response = await fetchImpl(`${base}${COPILOT_STATUS_PATH}`, init);
  let body: unknown;
  try {
    body = JSON.parse(await response.text());
  } catch {
    body = undefined;
  }
  if (!response.ok) {
    throw errorFromResponse({
      status: response.status,
      body,
      retryAfterHeader: response.headers.get("Retry-After"),
      correlationId: response.headers.get(CORRELATION_HEADER) ?? correlationId,
    });
  }
  if (typeof body === "object" && body !== null) {
    const record = body as Record<string, unknown>;
    const state = record["state"];
    const reason = record["reason_code"];
    if (state === "ready" || state === "disabled" || state === "failed") {
      return { state, reason_code: typeof reason === "string" ? reason : null };
    }
  }
  throw new Error("The copilot status response was not understood");
}

/**
 * The deployment's copilot state, fetched each time `active` turns true (the dock opens). `null`
 * while loading or when the probe itself failed: the composer then stays available, because the
 * message POST is the authority and reports the real failure.
 */
export function useCopilotStatus(
  transport: StreamTransport | null,
  active: boolean,
): CopilotStatus | null {
  const [status, setStatus] = useState<CopilotStatus | null>(null);
  useEffect(() => {
    if (!active || transport === null) return;
    const controller = new AbortController();
    fetchCopilotStatus(transport, controller.signal).then(
      (next) => {
        if (!controller.signal.aborted) setStatus(next);
      },
      () => {
        if (!controller.signal.aborted) setStatus(null);
      },
    );
    return () => controller.abort();
  }, [transport, active]);
  return status;
}
