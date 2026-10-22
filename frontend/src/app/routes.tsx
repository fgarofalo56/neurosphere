import type { ReactElement } from "react";
import type { RouteObject } from "react-router";
import { overviewRoutes } from "../features/overview/routes";
import { type NavItem } from "./navigation";
import { Shell } from "./Shell";

// Features import `NavItem` from here; the definition lives in ./navigation.
export type { NavItem } from "./navigation";

export interface AppRoutesOptions {
  /** Route-registration seam: workspace routes (item 5) are appended as layout children. */
  readonly extraRoutes?: readonly RouteObject[];
  /** Entries shown in the navigation slot. */
  readonly navItems?: readonly NavItem[];
  /** Dynamic nav (a hook, so it may read auth roles). Takes precedence over navItems. */
  readonly useNavItems?: () => readonly NavItem[];
}

const DEFAULT_NAV: readonly NavItem[] = [{ to: "/", label: "Home" }];

function NotFoundPage(): ReactElement {
  return (
    <section>
      <h1>Page not found</h1>
      <p>The page you requested does not exist.</p>
    </section>
  );
}

export function createAppRoutes(options: AppRoutesOptions = {}): RouteObject[] {
  const staticItems = options.navItems ?? DEFAULT_NAV;
  const useNavItems = options.useNavItems;
  function Layout(): ReactElement {
    return <Shell staticItems={staticItems} useNavItems={useNavItems} />;
  }
  return [
    {
      path: "/",
      Component: Layout,
      children: [
        // The home route comes from the overview feature, so replacing it never edits the shell.
        ...overviewRoutes,
        ...(options.extraRoutes ?? []),
        { path: "*", Component: NotFoundPage },
      ],
    },
  ];
}
