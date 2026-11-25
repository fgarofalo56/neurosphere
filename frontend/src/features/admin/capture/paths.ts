/**
 * Path constants for the interaction capture admin page (PRP-103 item 5). Kept free of heavy
 * imports so the areas list and the route table can reference them without loading Fluent UI.
 *
 * API (services/api/openapi.json, PRP-103 item 5), all GET and read-only:
 * - GET /api/v1/admin/interactions/capture-policies?domain_id&limit
 * - GET /api/v1/admin/interactions/capture-policies/{policy_id}
 * - GET /api/v1/admin/interactions/capture-status?domain_id
 * Without `domain_id` the API needs customer-level `config.manage`.
 */
export const ADMIN_CAPTURE_ROUTE = "admin/capture";
export const ADMIN_CAPTURE_API = "/api/v1/admin/interactions";

export const capturePaths = {
  policies: (): string => `${ADMIN_CAPTURE_API}/capture-policies`,
  policy: (policyId: string): string =>
    `${ADMIN_CAPTURE_API}/capture-policies/${encodeURIComponent(policyId)}`,
  status: (): string => `${ADMIN_CAPTURE_API}/capture-status`,
};
