/*
 * GENERATED - do not edit.
 * Source of truth: packages/contracts/schemas/ (JSON Schema 2020-12).
 * Regenerate: python packages/contracts/scripts/generate.py
 * Drift check: python packages/contracts/scripts/generate.py --check (ADR-0004).
 */

/**
 * What happened; open-ended: readers must tolerate unknown values.
 */
export type NotificationEventClass =
  | "policy_violation_opened"
  | "policy_violation_escalated"
  | "policy_violation_resolved"
  | "policy_exception_requested"
  | "policy_exception_decided"
  | "hitl_item_assigned"
  | "hitl_item_escalated"
  | "hitl_item_expiring"
  | "approval_requested"
  | "approval_decided"
  | "action_executed"
  | "action_failed"
  | "capture_policy_changed"
  | "enforcement_mode_changed"
  | "budget_threshold_crossed"
  | "channel_delivery_failed";
/**
 * How serious a violation of the policy or rule is.
 */
export type PolicySeverity = "low" | "medium" | "high" | "critical";

/**
 * One queued or sent notification (PRP-99; container notification_outbox). Metadata only: a short title and an application-relative link. There is no recipient address, no body and no content of any kind; recipients resolve inside the sender and are never stored. Named NotificationDelivery to avoid the DOM Notification type.
 */
export interface NotificationDelivery {
  /**
   * Contract version of the document; major 1 for every catalog v1 schema.
   */
  schema_version: string;
  notification_id: string;
  /**
   * Sovereign cloud boundary. Government data is never bridged to Commercial.
   */
  cloud: "commercial" | "government";
  /**
   * Customer segment of the canonical ID grammar.
   */
  customer_id: string;
  /**
   * Owning domain; authorization scope anchor. Canonical ID (canonical_id.schema.json) whose type segment is 'domain'.
   */
  domain_id: string;
  /**
   * Lowercase operator-chosen identifier.
   */
  channel_id: string;
  /**
   * Lowercase operator-chosen identifier.
   */
  subscription_id: string;
  event_class: NotificationEventClass;
  severity: PolicySeverity;
  subject: TargetRef;
  /**
   * Short headline, 1 to 160 characters, no control characters.
   */
  title: string;
  /**
   * Application-relative path to the item in the console, never an absolute URL.
   */
  link: string;
  correlation_id: string;
  /**
   * Digest of event class, subject and channel so one event is one delivery inside the dedup window.
   */
  dedup_key: string;
  status: "pending" | "sending" | "delivered" | "failed" | "dead_lettered" | "suppressed";
  attempts: number;
  next_attempt_at?: string | null;
  last_error_code?: string | null;
  /**
   * RFC 3339 timestamp in UTC (Z suffix required; no offsets).
   */
  created_at: string;
  delivered_at?: string | null;
  /**
   * Audit record of the event that caused the notification.
   */
  source_audit_id?: string | null;
}
/**
 * Reference to the resource an action changes or an audit record concerns. `canonical_id` uses the catalog grammar `cloud:customer:source:type:id` (Clarification 7); the pattern here mirrors it and the catalog/v1 grammar is authoritative. Python validator `validate_target_ref_matches_catalog_grammar` in tests/contracts/test_canonical_ids.py checks this pattern against the catalog ID corpus so the two cannot drift. The version being acted on is carried beside this object (ActionIntent.target_version), not inside it, so it is hashed as its own field.
 */
export interface TargetRef {
  /**
   * Cloud/customer/source qualified canonical ID of the target.
   */
  canonical_id: string;
  /**
   * Catalog entity type of the target, lowercase snake_case (for example `model_deployment`, `agent_version`).
   */
  entity_type: string;
}
