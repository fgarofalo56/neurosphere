/**
 * Path constants for the reports feature. Kept free of heavy imports so `index.ts` and the app
 * shell can reference routes without loading Fluent UI or the chart sandbox.
 *
 * The domain is the addressed resource (a path segment), not a scope claim: the shared client
 * refuses `domain_id`/`customer_id` as parameters and the server authorizes the domain against
 * the derived IdentityScope.
 */
export const REPORTS_API_PREFIX = "/api/v1/reports";

export const REPORTS_LIST_ROUTE = "reports";
export const REPORT_VIEW_ROUTE = "reports/view";

export function reportsPath(domainId: string): string {
  return `${REPORTS_API_PREFIX}/domains/${encodeURIComponent(domainId)}/reports`;
}

export function reportPath(domainId: string, reportId: string): string {
  return `${reportsPath(domainId)}/${encodeURIComponent(reportId)}`;
}

export function reportRunPath(domainId: string, reportId: string): string {
  return `${reportPath(domainId, reportId)}/run`;
}

export function reportSharesPath(domainId: string, reportId: string): string {
  return `${reportPath(domainId, reportId)}/shares`;
}

export function reportSharePath(domainId: string, reportId: string, principalId: string): string {
  return `${reportSharesPath(domainId, reportId)}/${encodeURIComponent(principalId)}`;
}

export function reportPublicationPath(domainId: string, reportId: string): string {
  return `${reportPath(domainId, reportId)}/publication`;
}

export function reportDecisionPath(domainId: string, reportId: string): string {
  return `${reportPublicationPath(domainId, reportId)}/decision`;
}

/** App route (not API) of one report; the page reads `domain_id` and `report_id` from it. */
export function reportViewHref(domainId: string, reportId: string): string {
  const p = new URLSearchParams({ domain_id: domainId, report_id: reportId });
  return `/${REPORT_VIEW_ROUTE}?${p.toString()}`;
}
