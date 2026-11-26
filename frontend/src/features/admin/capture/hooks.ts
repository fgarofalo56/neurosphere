import { useAdminGet } from "../shared/transport";
import { capturePaths } from "./paths";
import type { CapturePolicyPage, CapturePolicyView, CaptureStatus } from "./types";

export const CAPTURE_POLICIES_KEY = "admin-capture-policies";
export const CAPTURE_POLICY_KEY = "admin-capture-policy";
export const CAPTURE_STATUS_KEY = "admin-capture-status";

/** Every capture policy of the customer (customer-level `config.manage`; the API decides). */
export function useCapturePolicies() {
  return useAdminGet<CapturePolicyPage>(CAPTURE_POLICIES_KEY, {
    path: capturePaths.policies(),
    query: { limit: 200 },
  });
}

/** One policy, read when the user opens its detail. */
export function useCapturePolicy(policyId: string | null) {
  return useAdminGet<CapturePolicyView>(
    CAPTURE_POLICY_KEY,
    { path: capturePaths.policy(policyId ?? "") },
    policyId !== null,
  );
}

export function useCaptureStatus() {
  return useAdminGet<CaptureStatus>(CAPTURE_STATUS_KEY, { path: capturePaths.status() });
}
