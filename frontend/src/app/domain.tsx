import { useMsal } from "@azure/msal-react";
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactElement,
  type ReactNode,
} from "react";
import { useSearchParams } from "react-router";
import { ForbiddenError, createQueryHook } from "../api/index.js";

/**
 * Domain selection for the app shell and every domain-scoped page.
 *
 * The caller's readable domains come from `GET /api/v1/me/domains` (the server derives them from
 * the token; the client sends no scope). Selection lives in the URL (`?domain_id=`). The last
 * selection is remembered in `localStorage` as the domain ID ONLY, under a pseudonymous per-user
 * key, and is cleared on sign-out. That is the only thing this app writes to `localStorage`;
 * tokens and auth state stay in `sessionStorage` (PRP-04 rule C8, see auth/msal.ts).
 */

export type DomainNameSource = "catalog" | "derived";

/** One item of the `/me/domains` response. */
export interface DomainEntry {
  readonly domain_id: string;
  readonly display_name: string;
  readonly display_name_source: DomainNameSource;
  readonly cloud: "commercial" | "government";
  readonly permissions: readonly string[];
}

interface MeDomainsResponse {
  readonly items: readonly DomainEntry[];
}

export type DomainsStatus = "loading" | "ready" | "forbidden" | "error";

export const DOMAIN_PARAM = "domain_id";
export const LAST_DOMAIN_KEY_PREFIX = "ns.lastDomain.";
export const NO_DOMAINS_MESSAGE = "No domains are assigned to you";
export const NAME_UNAVAILABLE = "name unavailable";

export const ME_DOMAINS_PATH = "/api/v1/me/domains";

const useMeDomains = createQueryHook<Record<string, never>, MeDomainsResponse>({
  key: "me-domains",
  fetcher: (client, _params, signal) =>
    client.get<MeDomainsResponse>(ME_DOMAINS_PATH, undefined, signal),
});

/** Text shown for a domain: the catalog name, or the ID labelled "name unavailable". */
export function domainLabel(domain: DomainEntry): string {
  if (domain.display_name_source === "derived" || domain.display_name.trim() === "") {
    return `${domain.domain_id} (${NAME_UNAVAILABLE})`;
  }
  return domain.display_name;
}

/**
 * Pseudonymous storage key suffix: the first 128 bits of SHA-256 over the account's
 * homeAccountId, hex. The raw ID and the e-mail never reach storage. Returns null when Web
 * Crypto is unavailable (for example a non-secure origin): then nothing is persisted.
 */
export async function pseudonymousUserKey(homeAccountId: string): Promise<string | null> {
  const subtle = globalThis.crypto?.subtle;
  if (subtle === undefined || homeAccountId === "") return null;
  const bytes = new TextEncoder().encode(`ns.lastDomain.v1:${homeAccountId}`);
  const digest = new Uint8Array(await subtle.digest("SHA-256", bytes));
  return Array.from(digest.slice(0, 16), (b) => b.toString(16).padStart(2, "0")).join("");
}

export function lastDomainStorageKey(userKey: string): string {
  return `${LAST_DOMAIN_KEY_PREFIX}${userKey}`;
}

function readStored(key: string): string | null {
  try {
    return globalThis.localStorage.getItem(key);
  } catch {
    return null;
  }
}

function writeStored(key: string, value: string): void {
  try {
    globalThis.localStorage.setItem(key, value);
  } catch {
    // Storage blocked: the selection simply is not remembered.
  }
}

function removeStored(key: string): void {
  try {
    globalThis.localStorage.removeItem(key);
  } catch {
    // Nothing to clear.
  }
}

interface DomainData {
  readonly status: DomainsStatus;
  readonly domains: readonly DomainEntry[];
  /** Remembered domain if still readable, else the first readable one, else undefined. */
  readonly defaultDomainId: string | undefined;
  /** Union of permissions held across the readable domains. */
  readonly permissions: ReadonlySet<string>;
  readonly remember: (domainId: string) => void;
  /** Removes the remembered domain (sign-out). */
  readonly forget: () => void;
}

const DomainContext = createContext<DomainData | null>(null);

/** Shell-level access to the domain list; null when no provider is mounted. */
export function useDomainData(): DomainData | null {
  return useContext(DomainContext);
}

/**
 * Fetches the readable domains once the caller is signed in and holds the remembered selection.
 * Mounted in `Providers` (inside auth + query, outside the router).
 */
export function DomainProvider({ children }: { readonly children: ReactNode }): ReactElement {
  const { instance, accounts } = useMsal();
  const account = instance.getActiveAccount() ?? accounts[0] ?? null;
  const homeAccountId = account?.homeAccountId ?? "";

  const [userKey, setUserKey] = useState<string | null>(null);
  const [stored, setStored] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    void pseudonymousUserKey(homeAccountId).then(
      (key) => {
        if (cancelled) return;
        setUserKey(key);
        setStored(key === null ? null : readStored(lastDomainStorageKey(key)));
      },
      () => {
        if (!cancelled) setUserKey(null);
      },
    );
    return () => {
      cancelled = true;
    };
  }, [homeAccountId]);

  const query = useMeDomains({});
  const domains = useMemo(() => query.data?.items ?? [], [query.data]);
  const status: DomainsStatus = query.isPending
    ? "loading"
    : query.isError
      ? query.error instanceof ForbiddenError
        ? "forbidden"
        : "error"
      : "ready";

  const remember = useCallback(
    (domainId: string): void => {
      if (userKey === null) return;
      writeStored(lastDomainStorageKey(userKey), domainId);
      setStored(domainId);
    },
    [userKey],
  );
  const forget = useCallback((): void => {
    if (userKey !== null) removeStored(lastDomainStorageKey(userKey));
    setStored(null);
  }, [userKey]);

  const value = useMemo<DomainData>(() => {
    const restored =
      stored !== null && domains.some((d) => d.domain_id === stored) ? stored : undefined;
    const permissions = new Set<string>();
    for (const d of domains) for (const p of d.permissions) permissions.add(p);
    return {
      status,
      domains,
      defaultDomainId: restored ?? domains[0]?.domain_id,
      permissions,
      remember,
      forget,
    };
  }, [status, domains, stored, remember, forget]);

  return <DomainContext.Provider value={value}>{children}</DomainContext.Provider>;
}

export interface SelectedDomain {
  /**
   * The domain the page should show. The URL's `domain_id` is the source of truth; with none in
   * the URL it falls back to the remembered (or first readable) domain, and is "" until the list
   * has loaded. A URL domain the caller cannot read is returned as-is: the API answers 403.
   */
  readonly domainId: string;
  /** Domains the caller may read (empty until loaded, or when none are assigned). */
  readonly domains: readonly DomainEntry[];
  /** Selects a domain: sets `?domain_id=` on the current page and remembers the choice. */
  readonly setDomain: (domainId: string) => void;
  readonly status: DomainsStatus | "unavailable";
}

const NO_DOMAINS: readonly DomainEntry[] = [];

/**
 * THE hook for domain-scoped pages. Use `domainId` in place of a per-page domain text box and
 * put it in API paths (never in query or body: the API client refuses `domain_id` there).
 */
export function useSelectedDomain(): SelectedDomain {
  const data = useDomainData();
  const [params, setParams] = useSearchParams();
  const fromUrl = params.get(DOMAIN_PARAM)?.trim() ?? "";
  const remember = data?.remember;

  const setDomain = useCallback(
    (domainId: string): void => {
      setParams((prev) => {
        const next = new URLSearchParams(prev);
        next.set(DOMAIN_PARAM, domainId);
        return next;
      });
      remember?.(domainId);
    },
    [setParams, remember],
  );

  return {
    domainId: fromUrl !== "" ? fromUrl : (data?.defaultDomainId ?? ""),
    domains: data?.domains ?? NO_DOMAINS,
    setDomain,
    status: data?.status ?? "unavailable",
  };
}
