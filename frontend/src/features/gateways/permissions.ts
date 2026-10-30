import type { DomainEntry } from "../../app/domain";

export const ACTION_PROPOSE = "action.propose";

/**
 * Whether a control that drafts an action intent should be enabled in `domainId`. A known domain
 * without `action.propose` disables the control; an unknown domain (list not loaded, or a deep
 * link outside the list) leaves it enabled because the API is the authority and answers 403.
 * Hiding a control is a usability aid, never authorization.
 */
export function canPropose(domains: readonly DomainEntry[], domainId: string): boolean {
  const entry = domains.find((d) => d.domain_id === domainId);
  return entry === undefined ? true : entry.permissions.includes(ACTION_PROPOSE);
}
