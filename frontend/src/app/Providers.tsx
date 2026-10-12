import type { ReactElement, ReactNode } from "react";

/**
 * SINGLE PLACE for provider composition.
 * The integrator wires FluentProvider (design-system), AuthProvider (auth) and
 * QueryProvider (api) here, outermost first. FluentProvider must wrap the auth
 * provider so the login redirect screen is themed.
 */
export function Providers({ children }: { readonly children: ReactNode }): ReactElement {
  return <>{children}</>;
}
