import { createMutationHook, createQueryHook } from "../../api/index.js";
import type {
  ActionListResponse,
  ActionView,
  ConfirmVars,
  DetailParams,
  DraftVars,
  EmergencyDisableView,
  IntentVars,
  ListParams,
} from "./types";

/**
 * The domain is the addressed resource (a path segment), not a scope claim: the shared client
 * refuses `domain_id`/`customer_id` as parameters, and the server authorizes the domain against
 * the derived IdentityScope (403 when outside it).
 */
export function intentsPath(domainId: string): string {
  return `/api/v1/actions/domains/${encodeURIComponent(domainId)}/intents`;
}

export function intentPath(domainId: string, intentId: string): string {
  return `${intentsPath(domainId)}/${encodeURIComponent(intentId)}`;
}

export const EMERGENCY_DISABLE_PATH = "/api/v1/actions/emergency-disable";

export const useActionList = createQueryHook<ListParams, ActionListResponse>({
  key: "actions-list",
  fetcher: (client, p, signal) =>
    client.get<ActionListResponse>(
      intentsPath(p.domainId),
      {
        state: p.state === "" ? undefined : p.state,
        cursor: p.cursor === "" ? undefined : p.cursor,
        limit: p.limit,
      },
      signal,
    ),
});

export const useAction = createQueryHook<DetailParams, ActionView>({
  key: "actions-detail",
  fetcher: (client, p, signal) =>
    client.get<ActionView>(intentPath(p.domainId, p.intentId), undefined, signal),
});

export const useEmergencyDisable = createQueryHook<Record<string, never>, EmergencyDisableView>({
  key: "actions-emergency-disable",
  fetcher: (client, _p, signal) =>
    client.get<EmergencyDisableView>(EMERGENCY_DISABLE_PATH, undefined, signal),
});

export const useDraftIntent = createMutationHook<DraftVars, ActionView>({
  mutate: (client, v) => client.post<ActionView>(intentsPath(v.domainId), v.request),
});

export const useValidateIntent = createMutationHook<IntentVars, ActionView>({
  mutate: (client, v) => client.post<ActionView>(`${intentPath(v.domainId, v.intentId)}/validate`),
});

export const usePresentConfirmation = createMutationHook<IntentVars, ActionView>({
  mutate: (client, v) =>
    client.post<ActionView>(`${intentPath(v.domainId, v.intentId)}/confirmation`),
});

/** Submits the confirmation hash the server issued; it is never recomputed client-side. */
export const useConfirmIntent = createMutationHook<ConfirmVars, ActionView>({
  mutate: (client, v) =>
    client.post<ActionView>(`${intentPath(v.domainId, v.intentId)}/confirm`, {
      confirmation_hash: v.confirmationHash,
    }),
});
