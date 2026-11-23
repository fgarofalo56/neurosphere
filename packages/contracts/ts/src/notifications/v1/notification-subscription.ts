/*
 * GENERATED - do not edit.
 * Source of truth: packages/contracts/schemas/ (JSON Schema 2020-12).
 * Regenerate: python packages/contracts/scripts/generate.py
 * Drift check: python packages/contracts/scripts/generate.py --check (ADR-0004).
 */

/**
 * What happened; open-ended: readers must tolerate unknown values.
 *
 * This interface was referenced by `NotificationSubscription`'s JSON-Schema
 * via the `definition` "event_class".
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
 * Lowest severity delivered.
 */
export type PolicySeverity = "low" | "medium" | "high" | "critical";

/**
 * Which event classes reach which channel and for which audience roles (PRP-99; body of admin_kind notification_subscription). Recipients are resolved inside the sender from the roles and are never stored.
 */
export interface NotificationSubscription {
  /**
   * Contract version of the document; major 1 for every catalog v1 schema.
   */
  schema_version: string;
  /**
   * Subscription id (slug).
   */
  subscription_id: string;
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
   * Channel this subscription delivers to.
   */
  channel_id: string;
  /**
   * @minItems 1
   * @maxItems 16
   */
  event_classes: [NotificationEventClass, ...NotificationEventClass[]];
  /**
   * Roles whose members receive the notification.
   *
   * @minItems 1
   * @maxItems 6
   *
   * Items: Platform role (NS-08). admin and security_auditor are privileged and always time-bound.
   */
  audience_roles: [
    "viewer" | "analyst" | "domain_steward" | "admin" | "security_auditor",
    ...("viewer" | "analyst" | "domain_steward" | "admin" | "security_auditor")[],
  ];
  min_severity?: PolicySeverity;
  enabled: boolean;
}
