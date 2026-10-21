import type { DraftIntentRequest, PatchOperation } from "./types";

export const MODEL_SWAP_ACTION_KIND = "model_deployment_swap";
export const MODEL_DEPLOYMENT_ENTITY_TYPE = "model_deployment";
/** The only diff paths the Foundry swap connector accepts. */
export const MODEL_NAME_PATH = "/properties/model/name";
export const MODEL_VERSION_PATH = "/properties/model/version";

export interface DraftIntentInput {
  /** Canonical id of the model deployment being swapped. */
  readonly canonicalId: string;
  /** Exact target version/ETag the diff was computed against. */
  readonly targetVersion: string;
  readonly newModelName: string;
  /** Optional; omitted from the diff when empty. */
  readonly newModelVersion?: string | undefined;
  /** Generated once per draft attempt so a retry replays instead of duplicating. */
  readonly idempotencyKey: string;
}

/**
 * Pure builder for the button flow's draft request. It carries the change and the idempotency
 * key only: identity, customer and domain are derived by the server, and the confirmation hash
 * is never computed here (the server returns it). Item 7 posts this builder's fixture and the
 * equivalent hand-written REST body and asserts identical confirmation hashes.
 */
export function buildDraftIntentRequest(input: DraftIntentInput): DraftIntentRequest {
  const operations: PatchOperation[] = [
    { op: "replace", path: MODEL_NAME_PATH, value: input.newModelName },
  ];
  const version = input.newModelVersion?.trim() ?? "";
  if (version !== "") {
    operations.push({ op: "replace", path: MODEL_VERSION_PATH, value: version });
  }
  const [first, ...rest] = operations;
  if (first === undefined) throw new Error("unreachable: a swap always has one operation");
  return {
    action_kind: MODEL_SWAP_ACTION_KIND,
    target: { canonical_id: input.canonicalId, entity_type: MODEL_DEPLOYMENT_ENTITY_TYPE },
    target_version: input.targetVersion,
    proposed_diff: { format: "json_patch", operations: [first, ...rest] },
    evidence: [],
    idempotency_key: input.idempotencyKey,
    channel: "button",
    dry_run: false,
  };
}
