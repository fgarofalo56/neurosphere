import { Link } from "react-router";
import type { ReactElement } from "react";
import { ForbiddenError, type ApiError } from "../../api/index.js";
import { ErrorState, StatusPill, type StatusTone } from "../../design-system";
import { ForbiddenState } from "../workspaces/ForbiddenState";
import { CATALOG_ENTITY_ROUTE } from "./paths";
import type { LifecycleName } from "./explorerTypes";

const LIFECYCLE_TONE: Readonly<Record<LifecycleName, StatusTone>> = {
  draft: "info",
  active: "success",
  deprecated: "warning",
  retired: "neutral",
};

export function LifecyclePill({ value }: { readonly value: LifecycleName }): ReactElement {
  return <StatusPill label={value} tone={LIFECYCLE_TONE[value]} />;
}

/** `/catalog/entity?entity_id=` link; the id goes through URLSearchParams (encoded once). */
export function EntityLink({
  id,
  children,
}: {
  readonly id: string;
  readonly children?: string;
}): ReactElement {
  const params = new URLSearchParams({ entity_id: id });
  return (
    <Link to={`/${CATALOG_ENTITY_ROUTE}?${params.toString()}`}>
      {children !== undefined && children !== "" ? children : id}
    </Link>
  );
}

/** Edge ids contain ":" and may contain "/": always encoded. */
export function edgeHref(edgeId: string): string {
  return `/catalog/edge?edge_id=${encodeURIComponent(edgeId)}`;
}

export function mapHref(domainId: string): string {
  return `/map?domain_id=${encodeURIComponent(domainId)}`;
}

/** A 403 shows the shared forbidden state; anything else a retryable error. */
export function QueryProblem({
  error,
  title,
  onRetry,
}: {
  readonly error: ApiError;
  readonly title: string;
  readonly onRetry: () => void;
}): ReactElement {
  if (error instanceof ForbiddenError) {
    return <ForbiddenState workspace="catalog" correlationId={error.correlationId} />;
  }
  return (
    <ErrorState
      title={title}
      message={error.correlationId === "" ? undefined : `Reference: ${error.correlationId}`}
      onRetry={onRetry}
      testId="query-error"
    />
  );
}

/** Saves one JSON document through a temporary link (no data leaves the browser). */
export function downloadJson(fileName: string, data: unknown): void {
  const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = fileName;
  anchor.click();
  URL.revokeObjectURL(url);
}
