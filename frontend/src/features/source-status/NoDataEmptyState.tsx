import { Link as FluentLink } from "@fluentui/react-components";
import type { ReactElement, ReactNode } from "react";
import { Link, useInRouterContext } from "react-router";
import { EmptyState } from "../../design-system";
import { useIsAdmin, useSourceStatus } from "./hooks";
import { CONNECTORS_HREF, SOURCE_LABELS, STRINGS } from "./strings";
import type { SourceKey, SourceStatusEntry } from "./types";

export interface NoDataLink {
  readonly label: string;
  readonly href: string;
}

export interface NoDataEmptyStateProps {
  /** What is missing, in the page's own words. This is the page's current empty text. */
  readonly what: string;
  /** The sources this page's data comes from. Empty: no source sentence, only the link. */
  readonly sources: readonly SourceKey[];
  /** Where an administrator connects the source. Defaults to the Connectors page. */
  readonly adminHref?: string;
  /** Visible text of the admin link when `adminHref` is not the Connectors page. */
  readonly adminLabel?: string;
  /** Extra links shown to everyone who may follow them (for example a role's own pages). */
  readonly extraLinks?: readonly NoDataLink[];
  readonly description?: ReactNode;
  readonly testId?: string;
}

function formatWhen(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return `${d.toISOString().slice(0, 16).replace("T", " ")} UTC`;
}

function PageLink({ href, children }: { readonly href: string; readonly children: ReactNode }) {
  const inRouter = useInRouterContext();
  if (inRouter) {
    return (
      <FluentLink as="span">
        <Link to={href}>{children}</Link>
      </FluentLink>
    );
  }
  return <FluentLink href={href}>{children}</FluentLink>;
}

function describe(entries: readonly SourceStatusEntry[]): {
  readonly text: string;
  readonly arrived: boolean;
} {
  const missing = entries.filter((e) => e.state === "not_connected" || e.state === "failing");
  if (missing.length === 0) {
    const times = entries
      .map((e) => e.last_success_at)
      .filter((t): t is string => t !== null)
      .sort();
    const last = times[times.length - 1];
    const tail = last === undefined ? STRINGS.noSuccessYet : STRINGS.lastSuccess(formatWhen(last));
    return { text: `${STRINGS.notArrivedYet} ${tail}`, arrived: true };
  }
  const names = missing.map((e) => {
    const base = SOURCE_LABELS[e.source];
    if (!e.available) return `${base} ${STRINGS.unavailableSuffix}`;
    return e.state === "failing" ? `${base} ${STRINGS.failingSuffix}` : base;
  });
  const prefix = names.length > 1 ? STRINGS.notConnectedPrefixPlural : STRINGS.notConnectedPrefix;
  return { text: `${prefix} ${names.join(", ")}.`, arrived: false };
}

/** The admin link, or the sentence for everyone else. For panels that are not `EmptyState`. */
export function AdminActionLink({
  href,
  label,
  testId = "source-status-admin-link",
}: {
  readonly href: string;
  readonly label: string;
  readonly testId?: string;
}): ReactElement {
  const isAdmin = useIsAdmin();
  return isAdmin ? (
    <span data-testid={testId}>
      <PageLink href={href}>{label}</PageLink>
    </span>
  ) : (
    <span data-testid="source-status-ask-admin">{STRINGS.askAdmin}</span>
  );
}

/**
 * Source-aware "nothing here" panel. While the status is loading, and when it cannot be read (403
 * or any error), it renders the page's own text unchanged. Otherwise it says which source is
 * missing, or that data has not arrived yet, and points an administrator at the page that
 * connects it; everyone else is told to ask one.
 */
export function NoDataEmptyState({
  what,
  sources,
  adminHref = CONNECTORS_HREF,
  adminLabel,
  extraLinks = [],
  description,
  testId,
}: NoDataEmptyStateProps): ReactElement {
  const status = useSourceStatus();
  // A page with no source behind it (`sources` empty) always shows its link; the others wait for
  // the status and keep their own text when it cannot be read.
  if (sources.length > 0 && status.sources === undefined) {
    return <EmptyState title={what} description={description} testId={testId} />;
  }
  const inScope = (status.sources ?? []).filter((s) => sources.includes(s.source));
  // A source that is not available in this release cannot be connected: it only counts when nothing else does.
  const available = inScope.filter((s) => s.available);
  const relevant = available.length > 0 ? available : inScope;
  const detail = relevant.length > 0 ? describe(relevant) : undefined;
  const action = (
    <>
      {extraLinks.map((l) => (
        <PageLink key={l.href} href={l.href}>
          {l.label}
        </PageLink>
      ))}
      <AdminActionLink href={adminHref} label={adminLabel ?? STRINGS.connectLink} />
    </>
  );
  return (
    <EmptyState
      title={what}
      description={
        detail === undefined ? (
          description
        ) : (
          <>
            {description === undefined ? null : <>{description} </>}
            <span data-testid="source-status-detail">{detail.text}</span>
          </>
        )
      }
      action={action}
      testId={testId}
    />
  );
}
