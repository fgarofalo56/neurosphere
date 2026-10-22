import { createContext, useContext, useMemo, type ReactElement, type ReactNode } from "react";
import { ConfigContext } from "../../app/ConfigContext";
import { getToken } from "../../auth/token";
import type { StreamTransport } from "./stream";

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
