import { Button, makeStyles, tokens } from "@fluentui/react-components";
import { useId, useState, type ReactElement } from "react";
import { ForbiddenError, StaleVersionError, type ApiError } from "../../../api/index.js";
import { ErrorState } from "../../../design-system";
import { useMyAccess } from "../identity/hooks";
import type { AccessRoleView } from "../identity/types";
import { ADMIN_STRINGS } from "./strings";

function referenceOf(error: ApiError): string {
  return error.correlationId !== "" ? ` (${ADMIN_STRINGS.reference} ${error.correlationId})` : "";
}

/** Reason codes whose permission is needed on the customer control domain (PRP-138). */
export const DEPLOYMENT_SCOPE_REASONS: ReadonlySet<string> = new Set(["customer_scope_required"]);

/** One line per role the caller holds: role, source, entry, domain count, control flag, expiry. */
export function accessRoleText(role: AccessRoleView): string {
  const A = ADMIN_STRINGS.access;
  const parts: string[] = [role.role, A.sources[role.source]];
  if (role.mapping_entry_id !== null) parts.push(A.entry(role.mapping_entry_id));
  parts.push(A.domains(role.domain_count));
  if (role.customer_control) parts.push(A.wholeDeployment);
  parts.push(role.expires_at === null ? A.noExpiry : A.expires(role.expires_at));
  return parts.join(", ");
}

function AccessBody(): ReactElement {
  const A = ADMIN_STRINGS.access;
  const query = useMyAccess(null);
  if (query.isError) return <p data-testid="access-disclosure-error">{A.failed}</p>;
  if (query.isPending) return <p aria-busy="true">{A.loading}</p>;
  const { roles, groups_overage: overage } = query.data;
  return (
    <>
      {overage ? <p data-testid="access-disclosure-overage">{A.overage}</p> : null}
      {roles.length === 0 ? (
        <p data-testid="access-disclosure-none">{A.none}</p>
      ) : (
        <ul>
          {roles.map((role, i) => (
            <li key={`${role.role}-${role.source}-${i}`} data-testid="access-disclosure-role">
              {accessRoleText(role)}
            </li>
          ))}
        </ul>
      )}
    </>
  );
}

/**
 * "Your access" disclosure: closed by default, and only when opened does it read
 * `/api/v1/me/access` (any authenticated caller may), so a denied user on any admin page can see
 * what they hold.
 */
export function YourAccessDisclosure(): ReactElement {
  const [open, setOpen] = useState(false);
  const regionId = useId();
  return (
    <div data-testid="access-disclosure">
      <Button
        size="small"
        appearance="secondary"
        aria-expanded={open}
        aria-controls={regionId}
        onClick={() => setOpen(!open)}
      >
        {ADMIN_STRINGS.access.disclosure}
      </Button>
      <div id={regionId} hidden={!open} data-testid="access-disclosure-content">
        {open ? <AccessBody /> : null}
      </div>
    </div>
  );
}

/**
 * Page-level read failure. 403 is a forbidden state (the API decided, not the nav); anything else
 * is a retryable outage. Never rendered as an empty list. The 403 state shows the API's detail
 * (which names the permission), whether it is needed on the whole deployment, and the caller's
 * own access behind a disclosure. `accessAnchor` adds an in-page link to a "Your access" panel;
 * `testIdPrefix` keeps a secondary panel's state apart from the page's own `forbidden-state`.
 */
export function QueryErrorState({
  error,
  onRetry,
  accessAnchor,
  testIdPrefix = "",
}: {
  readonly error: ApiError;
  readonly onRetry?: (() => void) | undefined;
  readonly accessAnchor?: string | undefined;
  readonly testIdPrefix?: string | undefined;
}): ReactElement {
  const ref = referenceOf(error);
  if (error instanceof ForbiddenError) {
    const detail = error.problem?.detail;
    const reason = error.problem?.reason;
    const wholeDeployment = reason !== undefined && DEPLOYMENT_SCOPE_REASONS.has(reason);
    return (
      <ErrorState
        tone="warning"
        title={ADMIN_STRINGS.forbidden}
        testId={`${testIdPrefix}forbidden-state`}
        message={
          <>
            {detail === undefined || detail === "" ? null : (
              <span
                data-testid={`${testIdPrefix}forbidden-detail`}
              >{`${detail.replace(/\.$/, "")}. `}</span>
            )}
            <span data-testid={`${testIdPrefix}forbidden-scope`}>
              {wholeDeployment ? ADMIN_STRINGS.forbiddenDeployment : ADMIN_STRINGS.forbiddenDomain}
            </span>{" "}
            {ADMIN_STRINGS.forbiddenDetail}
            {ref}
          </>
        }
        action={
          <>
            {accessAnchor === undefined ? null : (
              <a href={`#${accessAnchor}`} data-testid={`${testIdPrefix}forbidden-access-link`}>
                {ADMIN_STRINGS.forbiddenAccessLink}
              </a>
            )}
            <YourAccessDisclosure />
          </>
        }
      />
    );
  }
  return (
    <ErrorState
      title={ADMIN_STRINGS.unavailable}
      testId={`${testIdPrefix}unavailable-state`}
      action={
        onRetry === undefined ? undefined : (
          <Button size="small" onClick={onRetry}>
            {ADMIN_STRINGS.retry}
          </Button>
        )
      }
      message={
        <>
          {ADMIN_STRINGS.unavailableDetail}
          {ref}
        </>
      }
    />
  );
}

/**
 * Text for a failed write. 409 gets reload guidance; 403 and 422 show the API's own words (the
 * problem detail) unchanged so a reserved name or a bad expiry reads exactly as the server said.
 */
export function changeErrorText(error: ApiError): string {
  const ref = referenceOf(error);
  if (error instanceof StaleVersionError) return `${ADMIN_STRINGS.stale}${ref}`;
  if (error instanceof ForbiddenError) {
    return `${ADMIN_STRINGS.forbidden}: ${error.problem?.reason ?? ADMIN_STRINGS.forbiddenDetail}${ref}`;
  }
  return `${error.problem?.detail ?? error.message}${ref}`;
}

const useStyles = makeStyles({
  id: { display: "inline-flex", alignItems: "center", columnGap: tokens.spacingHorizontalXS },
  code: { overflowWrap: "anywhere" },
});

/** A pseudonymous id: shown as is with a copy button, never joined to a name. */
export function CopyableId({
  value,
  label,
}: {
  readonly value: string;
  readonly label: string;
}): ReactElement {
  const styles = useStyles();
  const [copied, setCopied] = useState(false);
  return (
    <span className={styles.id}>
      <code className={styles.code}>{value}</code>
      <Button
        size="small"
        appearance="subtle"
        aria-label={`${ADMIN_STRINGS.copy} ${label}`}
        onClick={() => {
          void navigator.clipboard?.writeText(value);
          setCopied(true);
        }}
      >
        {copied ? ADMIN_STRINGS.copied : ADMIN_STRINGS.copy}
      </Button>
    </span>
  );
}

/** Cursor paging control: first page (when past it) and next page (when the server has one). */
export function CursorPager({
  canGoFirst,
  next,
  onFirst,
  onNext,
}: {
  readonly canGoFirst: boolean;
  readonly next: string | null | undefined;
  readonly onFirst: () => void;
  readonly onNext: (cursor: string) => void;
}): ReactElement {
  return (
    <div style={{ display: "flex", columnGap: tokens.spacingHorizontalS }}>
      {canGoFirst ? <Button onClick={onFirst}>{ADMIN_STRINGS.firstPage}</Button> : null}
      {next !== null && next !== undefined ? (
        <Button onClick={() => onNext(next)}>{ADMIN_STRINGS.nextPage}</Button>
      ) : null}
    </div>
  );
}
