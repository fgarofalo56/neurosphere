import { Button, makeStyles, tokens } from "@fluentui/react-components";
import { useState, type ReactElement } from "react";
import { ForbiddenError, StaleVersionError, type ApiError } from "../../../api/index.js";
import { ErrorState } from "../../../design-system";
import { ADMIN_STRINGS } from "./strings";

function referenceOf(error: ApiError): string {
  return error.correlationId !== "" ? ` (${ADMIN_STRINGS.reference} ${error.correlationId})` : "";
}

/**
 * Page-level read failure. 403 is a forbidden state (the API decided, not the nav); anything else
 * is a retryable outage. Never rendered as an empty list.
 */
export function QueryErrorState({
  error,
  onRetry,
}: {
  readonly error: ApiError;
  readonly onRetry?: (() => void) | undefined;
}): ReactElement {
  const ref = referenceOf(error);
  if (error instanceof ForbiddenError) {
    return (
      <ErrorState
        tone="warning"
        title={ADMIN_STRINGS.forbidden}
        testId="forbidden-state"
        message={
          <>
            {ADMIN_STRINGS.forbiddenDetail}
            {ref}
          </>
        }
      />
    );
  }
  return (
    <ErrorState
      title={ADMIN_STRINGS.unavailable}
      testId="unavailable-state"
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
