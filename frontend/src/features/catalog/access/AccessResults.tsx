import { MessageBar, MessageBarBody, MessageBarTitle } from "@fluentui/react-components";
import type { ReactElement } from "react";
import { ForbiddenError, InvalidSchemaError, type ApiError } from "../../../api/index.js";
import { DataTable, ErrorState, StatusPill, Timestamp } from "../../../design-system";
import type { StatusTone } from "../../../design-system";
import { ForbiddenState } from "../../workspaces/ForbiddenState";
import { EntityLink } from "../explorerParts";
import { ACCESS_STRINGS as S } from "./strings";
import type { AccessAssetView, AccessRowView, EdgeStatus, TruncatedReason } from "./types";

const STATUS_TONE: Readonly<Record<EdgeStatus, StatusTone>> = {
  asserted: "success",
  inferred: "warning",
  curated: "info",
};

/** The status word is the meaning; the tone only reinforces it. */
export function EdgeStatusPill({ status }: { readonly status: EdgeStatus }): ReactElement {
  return <StatusPill label={S.status[status] ?? status} tone={STATUS_TONE[status]} />;
}

function confidenceText(value: number): string {
  return `${String(Math.round(value * 100))}%`;
}

function Evidence({ ids }: { readonly ids: readonly string[] }): ReactElement {
  if (ids.length === 0) return <span>{S.table.noEvidence}</span>;
  return (
    <ul aria-label={S.table.evidence} style={{ margin: 0, paddingLeft: "1em" }}>
      {ids.map((id) => (
        <li key={id}>
          <code>{id}</code>
        </li>
      ))}
    </ul>
  );
}

export interface ResultTableProps {
  readonly rows: readonly AccessRowView[];
  readonly label: string;
  /** Dependents have no access mode but do have a relation path. */
  readonly variant: "access" | "dependents";
}

/** The one result table every question uses. */
export function ResultTable({ rows, label, variant }: ResultTableProps): ReactElement {
  const dependents = variant === "dependents";
  return (
    <DataTable
      label={label}
      rows={rows}
      getRowId={(r) => `${r.asset_id}|${r.edge_id}|${r.accessor_id}`}
      getRowProps={(r) => ({ "data-testid": "access-row", "data-accessor": r.accessor_id })}
      columns={[
        {
          key: "accessor",
          header: S.table.accessor,
          render: (r) => <EntityLink id={r.accessor_id}>{r.accessor_name}</EntityLink>,
        },
        { key: "type", header: S.table.type, render: (r) => r.accessor_type },
        dependents
          ? {
              key: "path",
              header: S.dependents.path,
              render: (r) => <span>{r.relation_path.join(" > ")}</span>,
            }
          : {
              key: "mode",
              header: S.table.mode,
              render: (r) =>
                r.mode === "write"
                  ? S.table.modeWrite
                  : r.mode === "read"
                    ? S.table.modeRead
                    : r.relation,
            },
        ...(dependents
          ? []
          : [
              {
                key: "asset",
                header: S.table.asset,
                render: (r: AccessRowView) => <EntityLink id={r.asset_id} />,
              },
            ]),
        {
          key: "status",
          header: S.table.status,
          render: (r) => <EdgeStatusPill status={r.status} />,
        },
        {
          key: "confidence",
          header: S.table.confidence,
          render: (r) => confidenceText(r.confidence),
        },
        {
          key: "provenance",
          header: S.table.provenance,
          render: (r) => `${r.provenance_method} (${r.provenance_source_id})`,
        },
        {
          key: "last",
          header: S.table.lastObserved,
          render: (r) => <Timestamp value={r.last_observed} />,
        },
        {
          key: "evidence",
          header: S.table.evidence,
          render: (r) => <Evidence ids={r.evidence_ids} />,
        },
      ]}
    />
  );
}

/** Shown whenever a bound stopped the scan: a truncated result never reads as complete. */
export function PartialBanner({
  reason,
  scanned,
}: {
  readonly reason: TruncatedReason | null;
  readonly scanned: number;
}): ReactElement {
  const why =
    reason === null
      ? S.results.reasonUnknown
      : (S.results.reasons[reason] ?? S.results.reasonUnknown);
  return (
    <MessageBar intent="warning" role="status" data-testid="partial-banner">
      <MessageBarBody>
        <MessageBarTitle>{S.results.partialTitle}</MessageBarTitle>
        {S.results.partial(why, scanned)}
      </MessageBarBody>
    </MessageBar>
  );
}

function notAssessed(value: string | null | undefined): string {
  return value === null || value === undefined || value === "" ? S.notAssessed : value;
}

function personalData(value: boolean | null): string {
  if (value === null) return S.notAssessed;
  return value ? S.results.yes : S.results.no;
}

/** A null or empty sensitivity is "not assessed", never "none". */
export function categoriesText(value: readonly string[] | null): string {
  return value === null || value.length === 0 ? S.notAssessed : value.join(", ");
}

export function UnassessedTable({
  assets,
}: {
  readonly assets: readonly AccessAssetView[];
}): ReactElement {
  return (
    <DataTable
      label={S.results.unassessedTable}
      rows={assets}
      getRowId={(a) => a.id}
      getRowProps={(a) => ({ "data-testid": "unassessed-row", "data-asset": a.id })}
      columns={[
        {
          key: "asset",
          header: S.results.asset,
          render: (a) => <EntityLink id={a.id}>{a.display_name}</EntityLink>,
        },
        {
          key: "class",
          header: S.results.classification,
          render: (a) => notAssessed(a.classification),
        },
        { key: "region", header: S.results.region, render: (a) => notAssessed(a.residency_region) },
        {
          key: "pd",
          header: S.results.personalData,
          render: (a) => personalData(a.contains_personal_data),
        },
        {
          key: "cat",
          header: S.results.categories,
          render: (a) => categoriesText(a.sensitivity_categories),
        },
      ]}
    />
  );
}

function referenceText(error: ApiError): string {
  return error.correlationId === "" ? "" : S.errors.reference(error.correlationId);
}

/** 403 shows the shared forbidden state, 422 a human reason, anything else a retryable error. */
export function ProblemView({
  error,
  onRetry,
}: {
  readonly error: ApiError;
  readonly onRetry: () => void;
}): ReactElement {
  if (error instanceof ForbiddenError) {
    return <ForbiddenState workspace="catalog" correlationId={error.correlationId} />;
  }
  if (error instanceof InvalidSchemaError) {
    const reason = error.problem?.reason;
    const text =
      reason !== undefined && reason !== null
        ? (S.errors.validation[reason] ?? S.errors.validationFallback)
        : S.errors.validationFallback;
    return (
      <ErrorState
        tone="warning"
        title={S.errors.validationTitle}
        message={`${text}${referenceText(error)}`}
        testId="access-validation"
      />
    );
  }
  return (
    <ErrorState
      title={S.errors.title}
      message={`${S.errors.generic}${referenceText(error)}`}
      onRetry={onRetry}
      testId="access-error"
    />
  );
}
