/**
 * Response shapes of the read-only capture admin routes (PRP-103 item 5). Metadata and counters
 * only: a capture policy holds no content, and the status carries reason codes and integers.
 * Only the fields named here are rendered.
 */

export type CapturePolicyState = "proposed" | "active" | "suspended" | "retired";

export interface CaptureSampling {
  readonly rate: number;
  readonly max_per_minute: number;
}

export interface CapturePolicyView {
  readonly policy_id: string;
  readonly display_name: string;
  readonly version: number;
  readonly previous_version: number | null;
  readonly domain_id: string;
  readonly source_ids: readonly string[];
  readonly parts: readonly string[];
  readonly detector_set_version: string;
  readonly customer_dictionary_ids: readonly string[];
  readonly redaction_mode: string;
  readonly kept_categories: readonly string[];
  readonly sampling: CaptureSampling;
  readonly max_part_chars: number | null;
  readonly retention_class: string;
  readonly retention_days: number | null;
  readonly state: CapturePolicyState;
  readonly approved_intent_id: string | null;
  readonly approved_audit_id: string | null;
  readonly effective_from: string | null;
}

export interface CapturePolicyPage {
  readonly items: readonly CapturePolicyView[];
  readonly truncated: boolean;
  readonly configured: boolean;
  readonly reason: string | null;
}

export interface PolicyStateCounts {
  readonly total: number;
  readonly proposed: number;
  readonly active: number;
  readonly suspended: number;
  readonly retired: number;
}

export interface CaptureCounters {
  readonly captured: number;
  readonly capture_skipped_no_policy: number;
  readonly capture_skipped_item_cap: number;
  readonly skipped_reasons: Readonly<Record<string, number>>;
  readonly capture_failed: Readonly<Record<string, number>>;
  readonly capture_failed_total: number;
  readonly capture_shed: number;
  readonly shed_reasons: Readonly<Record<string, number>>;
  readonly audit_write_failed: number;
  readonly failure_record_failed: number;
  readonly cleanup_failed: number;
  readonly in_flight: number;
}

export interface CaptureStatus {
  readonly state: "active" | "off";
  readonly off_reason: string | null;
  readonly configured: boolean;
  readonly domain_id: string | null;
  readonly policies: PolicyStateCounts;
  readonly policies_truncated: boolean;
  readonly counters: CaptureCounters | null;
  readonly counters_scope: "customer";
}
