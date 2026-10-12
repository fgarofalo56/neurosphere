import type { ReactElement } from "react";
import { NavLink, Outlet, type RouteObject } from "react-router";
import { ErrorBoundary } from "./ErrorBoundary";

export interface NavItem {
  readonly to: string;
  readonly label: string;
}

export interface AppRoutesOptions {
  /** Route-registration seam: workspace routes (item 5) are appended as layout children. */
  readonly extraRoutes?: readonly RouteObject[];
  /** Entries shown in the navigation slot. */
  readonly navItems?: readonly NavItem[];
  /** Dynamic nav (a hook, so it may read auth roles). Takes precedence over navItems. */
  readonly useNavItems?: () => readonly NavItem[];
}

const DEFAULT_NAV: readonly NavItem[] = [{ to: "/", label: "Home" }];

function HomePage(): ReactElement {
  return (
    <section>
      <h1>NeuroSphere</h1>
      <p>AI governance workspace.</p>
    </section>
  );
}

function NotFoundPage(): ReactElement {
  return (
    <section>
      <h1>Page not found</h1>
      <p>The page you requested does not exist.</p>
    </section>
  );
}

function makeLayout(
  staticItems: readonly NavItem[],
  useNavItems: (() => readonly NavItem[]) | undefined,
): () => ReactElement {
  return function Layout(): ReactElement {
    const navItems = useNavItems === undefined ? staticItems : useNavItems();
    return (
      <div>
        <header>
          {/* Logo slot: intentionally empty, filled by theme packs (PRP-24). */}
          <div data-slot="logo" />
        </header>
        <nav aria-label="Primary" data-slot="navigation">
          <ul>
            {navItems.map((item) => (
              <li key={item.to}>
                <NavLink to={item.to} end={item.to === "/"}>
                  {item.label}
                </NavLink>
              </li>
            ))}
          </ul>
        </nav>
        <main id="main-content">
          <ErrorBoundary>
            <Outlet />
          </ErrorBoundary>
        </main>
      </div>
    );
  };
}

export function createAppRoutes(options: AppRoutesOptions = {}): RouteObject[] {
  const Layout = makeLayout(options.navItems ?? DEFAULT_NAV, options.useNavItems);
  return [
    {
      path: "/",
      Component: Layout,
      children: [
        { index: true, Component: HomePage },
        ...(options.extraRoutes ?? []),
        { path: "*", Component: NotFoundPage },
      ],
    },
  ];
}
