import { createMutationHook, createQueryHook } from "../../api/index.js";
import type {
  DecideVars,
  IntentParams,
  IntentSummary,
  ItemParams,
  ListParams,
  ReviewItemList,
  ReviewItemView,
} from "./types";

/**
 * The domain is the addressed resource (a path segment), not a scope claim: the shared client
 * refuses `domain_id`/`customer_id` as parameters, and the server authorizes the domain against
 * the derived IdentityScope (403 when outside it).
 */
export function itemsPath(domainId: string): string {
  return `/api/v1/review/domains/${encodeURIComponent(domainId)}/items`;
}

export function itemPath(domainId: string, itemId: string): string {
  return `${itemsPath(domainId)}/${encodeURIComponent(itemId)}`;
}

export function intentPath(domainId: string, intentId: string): string {
  return `/api/v1/actions/domains/${encodeURIComponent(domainId)}/intents/${encodeURIComponent(intentId)}`;
}

export const useReviewItems = createQueryHook<ListParams, ReviewItemList>({
  key: "review-items",
  fetcher: (client, p, signal) =>
    client.get<ReviewItemList>(
      itemsPath(p.domainId),
      {
        kind: p.kind === "" ? undefined : p.kind,
        state: p.state === "" ? undefined : p.state,
        cursor: p.cursor === "" ? undefined : p.cursor,
        limit: p.limit,
      },
      signal,
    ),
});

export const useReviewItem = createQueryHook<ItemParams, ReviewItemView>({
  key: "review-item",
  fetcher: (client, p, signal) =>
    client.get<ReviewItemView>(itemPath(p.domainId, p.itemId), undefined, signal),
});

/** The intent under maker-checker review: the reviewer sees its exact diff and server hash. */
export const useReviewedIntent = createQueryHook<IntentParams, IntentSummary>({
  key: "review-intent",
  fetcher: (client, p, signal) =>
    client.get<IntentSummary>(intentPath(p.domainId, p.intentId), undefined, signal),
});

/** `null` assignee claims the item for the caller. */
export const useClaimItem = createMutationHook<ItemParams, ReviewItemView>({
  mutate: (client, v) =>
    client.post<ReviewItemView>(`${itemPath(v.domainId, v.itemId)}/assignment`, {
      assignee_principal_id: null,
    }),
});

export const useDecideItem = createMutationHook<DecideVars, ReviewItemView>({
  mutate: (client, v) =>
    client.post<ReviewItemView>(`${itemPath(v.domainId, v.itemId)}/decisions`, {
      decision: v.decision,
      reason: v.reason,
      ...(v.confirmationHash !== undefined && { confirmation_hash: v.confirmationHash }),
    }),
});
