/** Shapes of the audit adapter responses; only what the page shows (the API is the contract). */

export interface AuditDomain {
  readonly domain_id: string;
  readonly display_name: string;
  readonly display_name_source: "catalog" | "derived";
}

export interface AuditDomainList {
  readonly items: readonly AuditDomain[];
}

export interface AuditActor {
  readonly principal_pseudonym: string;
  readonly principal_kind: string;
  readonly on_behalf_of: string | null;
}

export interface AuditSubject {
  readonly target: { readonly canonical_id: string; readonly entity_type: string };
  readonly target_version: string | null;
  readonly state_digest: string | null;
  readonly snapshot_ref: string | null;
}

export interface AuditOutcome {
  readonly result: string;
  readonly verified: boolean;
  readonly detail: string | null;
}

export interface AuditDenial {
  readonly code: string;
  readonly reason: string;
}

export interface AuditRecord {
  readonly schema_version: string;
  readonly audit_id: string;
  readonly chain_id: string;
  readonly sequence: number;
  readonly previous_hash: string | null;
  readonly record_hash: string;
  readonly kind: "before" | "after" | "denied";
  readonly recorded_at: string;
  readonly actor: AuditActor;
  readonly scope_hash: string;
  readonly correlation_id: string;
  readonly operation: string;
  readonly channel: string | null;
  readonly intent_id: string | null;
  readonly subject: AuditSubject | null;
  readonly outcome: AuditOutcome | null;
  readonly denial: AuditDenial | null;
}

export interface AuditRecordPage {
  readonly items: readonly AuditRecord[];
  readonly next_cursor: string | null;
}

export interface ChainVerification {
  readonly chain_id: string;
  readonly ok: boolean;
  readonly records_checked: number;
  readonly first_invalid_index: number | null;
  readonly first_invalid_sequence: number | null;
  readonly reason: string | null;
}
