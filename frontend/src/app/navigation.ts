import type { NsRole } from "../auth/roles";

/** Side navigation groups, in display order. */
export const NAV_GROUPS = [
  "Overview",
  "Cost & usage",
  "Agents",
  "Quality",
  "Governance",
  "Reports",
] as const;
export type NavGroup = (typeof NAV_GROUPS)[number];

export interface NavItem {
  readonly to: string;
  readonly label: string;
  /** Section the entry is listed under. Entries without a group render first, without a header. */
  readonly group?: NavGroup;
  /**
   * Show the entry only when the caller holds one of these display roles (from token claims).
   * Visibility is a usability aid; the API still decides every request.
   */
  readonly roles?: readonly NsRole[];
  /**
   * Show the entry only when the caller holds this permission in at least one readable domain
   * (from `GET /api/v1/me/domains`). Hidden until the list is known.
   */
  readonly permission?: string;
}

export interface NavVisibilityContext {
  readonly roles: readonly NsRole[];
  /** Union of the permissions the caller holds across readable domains. */
  readonly permissions: ReadonlySet<string>;
}

/**
 * Hiding an entry is NOT authorization: the route stays registered, a deep link still reaches the
 * page and the API answers 403 when the caller is not allowed.
 */
export function isNavItemVisible(item: NavItem, ctx: NavVisibilityContext): boolean {
  if (item.roles !== undefined && !item.roles.some((r) => ctx.roles.includes(r))) return false;
  if (item.permission !== undefined && !ctx.permissions.has(item.permission)) return false;
  return true;
}

export interface NavSection {
  readonly group: NavGroup | undefined;
  readonly items: readonly NavItem[];
}

/** Ungrouped entries first, then the groups in `NAV_GROUPS` order; empty groups are dropped. */
export function groupNavItems(items: readonly NavItem[]): NavSection[] {
  const sections: NavSection[] = [];
  const ungrouped = items.filter((i) => i.group === undefined);
  if (ungrouped.length > 0) sections.push({ group: undefined, items: ungrouped });
  for (const group of NAV_GROUPS) {
    const inGroup = items.filter((i) => i.group === group);
    if (inGroup.length > 0) sections.push({ group, items: inGroup });
  }
  return sections;
}

/** `to` with `domain_id` appended, for the current domain selection (empty id leaves it alone). */
export function withDomain(to: string, domainId: string): string {
  if (domainId === "") return to;
  const sep = to.includes("?") ? "&" : "?";
  return `${to}${sep}domain_id=${encodeURIComponent(domainId)}`;
}

/** The entry whose path best matches `pathname` (exact, or the longest prefix at a segment). */
export function selectedNavTo(items: readonly NavItem[], pathname: string): string | undefined {
  let best: string | undefined;
  for (const { to } of items) {
    const base = to.split("?")[0] ?? to;
    const hit = pathname === base || (base !== "/" && pathname.startsWith(`${base}/`));
    if (hit && (best === undefined || base.length > best.length)) best = base;
  }
  return best;
}
