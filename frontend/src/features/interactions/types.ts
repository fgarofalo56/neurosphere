/**
 * Interaction explorer wire types (PRP-104). The records, the purpose, the redacted content and
 * the export manifest are the PRP-99 contract types; the page and the export request mirror
 * services/api/neurosphere_api/interactions/models.py.
 */
import type {
  InteractionAccessPurpose,
  InteractionExportManifest,
  InteractionRecord,
  RedactedContent,
} from "@neurosphere/contracts";

export type {
  InteractionAccessPurpose,
  InteractionExportManifest,
  InteractionRecord,
  RedactedContent,
};

export type PurposeCode = InteractionAccessPurpose["purpose_code"];

/** The six purpose codes of `InteractionAccessPurpose`, in contract order. */
export const PURPOSE_CODES: readonly PurposeCode[] = [
  "incident_investigation",
  "policy_violation_review",
  "legal_hold_review",
  "data_subject_request",
  "security_review",
  "quality_review",
];

export type DetectedCategory = NonNullable<
  InteractionRecord["findings_summary"]
>[number]["category"];

/** The contract's detected categories (open-ended upstream; the filter offers the known ones). */
export const DETECTED_CATEGORIES: readonly DetectedCategory[] = [
  "private_key",
  "jwt",
  "bearer_token",
  "cloud_access_key",
  "vendor_api_key",
  "connection_string",
  "url_with_credentials",
  "password_assignment",
  "payment_card",
  "iban",
  "us_ssn",
  "email_address",
  "phone_number",
  "ip_address",
  "mac_address",
  "guid",
  "customer_dictionary_term",
  "customer_identifier_pattern",
  "other",
];

/** One page of `GET /api/v1/domains/{d}/interactions` (newest `captured_at` first). */
export interface InteractionPage {
  items: InteractionRecord[];
  continuation: string | null;
}

/** Search filters as the page holds them; empty strings mean "no filter". */
export interface InteractionFilters {
  readonly agentId: string;
  readonly principalId: string;
  readonly toolId: string;
  readonly dataAssetId: string;
  readonly detectedCategory: string;
  /** Typed UTC time (YYYY-MM-DD or YYYY-MM-DDTHH:MM), sent with a Z suffix. */
  readonly from: string;
  readonly to: string;
}

export const EMPTY_FILTERS: InteractionFilters = {
  agentId: "",
  principalId: "",
  toolId: "",
  dataAssetId: "",
  detectedCategory: "",
  from: "",
  to: "",
};

/** Body of `POST /api/v1/domains/{d}/interaction-exports`. */
export interface InteractionExportRequest {
  purpose: InteractionAccessPurpose;
  filters: InteractionExportManifest["filters"];
}
