/** Shapes of the notification admin API (contracts notifications/v1 plus the view envelopes). */

export type ChannelKind = "webhook" | "teams_webhook" | "email";
export type KindStatus = "buildable" | "degraded" | "not_built";

export interface ChannelKindInfo {
  readonly kind: ChannelKind;
  readonly status: KindStatus;
  readonly reason: string | null;
}

/** A reference to a Key Vault secret. Never the secret value. */
export interface KeyVaultReference {
  readonly kind: "key_vault_secret";
  readonly secret_uri: string;
}

export interface NotificationChannel {
  readonly schema_version: string;
  readonly channel_id: string;
  readonly cloud: "commercial" | "government";
  readonly customer_id: string;
  readonly domain_id: string;
  readonly display_name: string;
  readonly kind: ChannelKind;
  readonly allowed_host: string;
  readonly endpoint_credential: KeyVaultReference | null;
  readonly hmac_credential: KeyVaultReference | null;
  readonly local_sink: boolean;
  readonly local_sink_url: string | null;
  readonly enabled: boolean;
}

export const DELIVERY_STATUSES = [
  "pending",
  "sending",
  "delivered",
  "failed",
  "dead_lettered",
  "suppressed",
] as const;
export type DeliveryStatus = (typeof DELIVERY_STATUSES)[number];

export interface ChannelView {
  readonly channel: NotificationChannel;
  readonly version: number;
  readonly etag: string;
  readonly updated_at: string;
  readonly updated_by: string;
  readonly delivery_counts: Readonly<Record<DeliveryStatus, number>>;
  readonly last_error_code: string | null;
}

export const EVENT_CLASSES = [
  "policy_violation_opened",
  "policy_violation_escalated",
  "policy_violation_resolved",
  "policy_exception_requested",
  "policy_exception_decided",
  "hitl_item_assigned",
  "hitl_item_escalated",
  "hitl_item_expiring",
  "approval_requested",
  "approval_decided",
  "action_executed",
  "action_failed",
  "capture_policy_changed",
  "enforcement_mode_changed",
  "budget_threshold_crossed",
  "channel_delivery_failed",
] as const;
export type EventClass = (typeof EVENT_CLASSES)[number];

export const AUDIENCE_ROLES = [
  "viewer",
  "analyst",
  "domain_steward",
  "admin",
  "security_auditor",
  "interaction_investigator",
] as const;
export type AudienceRole = (typeof AUDIENCE_ROLES)[number];

export const SEVERITIES = ["low", "medium", "high", "critical"] as const;
export type Severity = (typeof SEVERITIES)[number];

export interface NotificationSubscription {
  readonly schema_version: string;
  readonly subscription_id: string;
  readonly cloud: "commercial" | "government";
  readonly customer_id: string;
  readonly domain_id: string;
  readonly channel_id: string;
  readonly event_classes: readonly EventClass[];
  readonly audience_roles: readonly AudienceRole[];
  readonly min_severity: Severity;
  readonly enabled: boolean;
}

export interface SubscriptionView {
  readonly subscription: NotificationSubscription;
  readonly version: number;
  readonly etag: string;
  readonly updated_at: string;
  readonly updated_by: string;
}

export interface NotificationDelivery {
  readonly notification_id: string;
  readonly channel_id: string;
  readonly subscription_id: string;
  readonly domain_id: string;
  readonly event_class: string;
  readonly severity: string;
  readonly title: string;
  readonly status: DeliveryStatus;
  readonly attempts: number;
  readonly next_attempt_at?: string | null;
  readonly last_error_code?: string | null;
  readonly created_at: string;
  readonly delivered_at?: string | null;
}

export interface TestSendResult {
  readonly ok: boolean;
  readonly status_code: number | null;
  readonly reason_code: string | null;
}

export interface Items<T> {
  readonly items: readonly T[];
}
