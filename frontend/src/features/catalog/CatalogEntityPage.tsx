import { Button, Field, Input, makeStyles, tokens } from "@fluentui/react-components";
import { useRef, useState, type ReactElement } from "react";
import { Link, useSearchParams } from "react-router";
import { ForbiddenError, StaleVersionError, type ApiError } from "../../api/index.js";
import {
  DataTable,
  EmptyState,
  LoadingState,
  PageTemplate,
  Panel,
  StatusPill,
  Timestamp,
} from "../../design-system";
import { ChangeConfirmDialog, type ChangeDiffRow } from "../governed-change";
import {
  useDeprecate,
  useEntity,
  useImpact,
  useNeighbors,
  useRecertify,
  useReloadEntity,
} from "./explorerHooks";
import { EntityLink, LifecyclePill, QueryProblem, edgeHref, mapHref } from "./explorerParts";
import { EXPLORER_STRINGS } from "./explorerStrings";
import type { CatalogEntityView, GraphResultView } from "./explorerTypes";
import { CATALOG_EXPLORER_ROUTE } from "./paths";

const S = EXPLORER_STRINGS.entity;
const L = S.lineage;

const useStyles = makeStyles({
  stack: { display: "flex", flexDirection: "column", rowGap: tokens.spacingVerticalM },
  row: {
    display: "flex",
    flexWrap: "wrap",
    alignItems: "flex-end",
    columnGap: tokens.spacingHorizontalM,
    rowGap: tokens.spacingVerticalS,
  },
});

function nameOf(result: GraphResultView, id: string): string {
  const node = result.nodes.find((n) => n.id === id);
  return node?.display_name ?? id;
}

function Truncation({ result }: { readonly result: GraphResultView }): ReactElement | null {
  if (!result.truncated) return null;
  return <p data-testid="lineage-truncated">{L.truncated(result.truncated_reason)}</p>;
}

function NeighborsTable({
  entity,
  result,
}: {
  readonly entity: CatalogEntityView;
  readonly result: GraphResultView;
}): ReactElement {
  if (result.edges.length === 0) {
    return (
      <>
        <Truncation result={result} />
        <EmptyState title={L.noNeighbors} testId="no-neighbors" />
      </>
    );
  }
  return (
    <>
      <Truncation result={result} />
      <DataTable
        label={L.neighborsTitle}
        rows={result.edges}
        getRowId={(e) => e.edge_id}
        getRowProps={(e) => ({ "data-testid": "neighbor-row", "data-edge": e.edge_id })}
        columns={[
          {
            key: "edge",
            header: L.table.edge,
            render: (e) => <Link to={edgeHref(e.edge_id)}>{e.edge_id}</Link>,
          },
          { key: "relation", header: L.table.relation, render: (e) => e.relation_type },
          {
            key: "direction",
            header: L.table.direction,
            render: (e) => (e.source_id === entity.id ? L.outgoing : L.incoming),
          },
          {
            key: "other",
            header: L.table.other,
            render: (e) => {
              const other = e.source_id === entity.id ? e.target_id : e.source_id;
              return <EntityLink id={other}>{nameOf(result, other)}</EntityLink>;
            },
          },
          {
            key: "status",
            header: L.table.status,
            render: (e) => (
              <StatusPill label={e.status} tone={e.status === "curated" ? "info" : "neutral"} />
            ),
          },
          { key: "confidence", header: L.table.confidence, render: (e) => e.confidence.toFixed(2) },
          {
            key: "map",
            header: L.table.map,
            render: (e) => <Link to={mapHref(e.domain_id)}>{L.showOnMap}</Link>,
          },
        ]}
      />
    </>
  );
}

function ImpactTable({ result }: { readonly result: GraphResultView }): ReactElement {
  if (result.paths.length === 0) {
    return (
      <>
        <Truncation result={result} />
        <EmptyState title={L.noImpact} testId="no-impact" />
      </>
    );
  }
  return (
    <>
      <Truncation result={result} />
      <DataTable
        label={L.impactTitle}
        rows={result.paths.map((p, i) => ({ ...p, key: `${String(i)}:${p.node_ids.join(">")}` }))}
        getRowId={(p) => p.key}
        getRowProps={() => ({ "data-testid": "impact-row" })}
        columns={[
          {
            key: "path",
            header: L.table.path,
            render: (p) => p.node_ids.map((id) => nameOf(result, id)).join(" > "),
          },
          { key: "hops", header: L.table.hops, render: (p) => String(p.edge_ids.length) },
          {
            key: "edges",
            header: L.table.edges,
            render: (p) =>
              p.edge_ids.map((id) => (
                <span key={id}>
                  <Link to={edgeHref(id)}>{id}</Link>{" "}
                </span>
              )),
          },
        ]}
      />
    </>
  );
}

function LineageSection({ entity }: { readonly entity: CatalogEntityView }): ReactElement {
  const [direction, setDirection] = useState<"downstream" | "upstream">("downstream");
  const neighbors = useNeighbors({ entityId: entity.id });
  const impact = useImpact({ entityId: entity.id, direction });
  return (
    <>
      <Panel
        title={L.neighborsTitle}
        actions={<Link to={mapHref(entity.domain_id)}>{L.showOnMap}</Link>}
      >
        {neighbors.isError ? (
          <QueryProblem
            error={neighbors.error}
            title={L.failed}
            onRetry={() => void neighbors.refetch()}
          />
        ) : neighbors.data === undefined ? (
          <LoadingState label={L.loading} rows={3} />
        ) : (
          <NeighborsTable entity={entity} result={neighbors.data} />
        )}
      </Panel>
      <Panel title={L.impactTitle}>
        <div>
          <Button
            appearance={direction === "downstream" ? "primary" : "secondary"}
            aria-pressed={direction === "downstream"}
            onClick={() => setDirection("downstream")}
          >
            {L.downstream}
          </Button>
          <Button
            appearance={direction === "upstream" ? "primary" : "secondary"}
            aria-pressed={direction === "upstream"}
            onClick={() => setDirection("upstream")}
          >
            {L.upstream}
          </Button>
        </div>
        {impact.isError ? (
          <QueryProblem
            error={impact.error}
            title={L.failed}
            onRetry={() => void impact.refetch()}
          />
        ) : impact.data === undefined ? (
          <LoadingState label={L.loading} rows={3} />
        ) : (
          <ImpactTable result={impact.data} />
        )}
      </Panel>
    </>
  );
}

function ownersOf(
  entity: CatalogEntityView,
  result: GraphResultView | undefined,
): readonly string[] {
  if (result === undefined) return [];
  return result.edges
    .filter((e) => e.relation_type === "owned_by" && e.source_id === entity.id)
    .map((e) => e.target_id);
}

function changeError(error: ApiError | null): string | null {
  if (error === null) return null;
  if (error instanceof StaleVersionError) return S.stale;
  if (error instanceof ForbiddenError) return S.forbidden;
  return S.changeFailed;
}

type Change = "deprecate" | "recertify" | null;

function Actions({ entity }: { readonly entity: CatalogEntityView }): ReactElement {
  const styles = useStyles();
  const reload = useReloadEntity();
  const deprecate = useDeprecate();
  const recertify = useRecertify();
  const [open, setOpen] = useState<Change>(null);
  const [days, setDays] = useState("365");
  const [done, setDone] = useState("");
  const triggerRef = useRef<HTMLElement | null>(null);
  const daysNumber = Number(days);
  const daysOk = Number.isInteger(daysNumber) && daysNumber >= 1 && daysNumber <= 730;
  const canDeprecate = entity.lifecycle_status === "draft" || entity.lifecycle_status === "active";
  const isOwner = entity.entity_type === "owner";
  const mutation = open === "recertify" ? recertify : deprecate;

  const diff: ChangeDiffRow[] =
    open === "recertify"
      ? [
          {
            field: "recertify_by",
            before: entity.recertify_by ?? S.never,
            after: S.recertifyByAfter(daysNumber),
          },
        ]
      : [{ field: "lifecycle_status", before: entity.lifecycle_status, after: "deprecated" }];

  const close = (): void => {
    setOpen(null);
    deprecate.reset();
    recertify.reset();
  };

  const submit = (): void => {
    const onSuccess = (next: CatalogEntityView): void => {
      setDone(S.changeDone(open === "recertify" ? S.recertified : S.deprecated, next.etag));
      close();
      void reload();
    };
    const onError = (): void => {
      // 409 or any refusal: re-read so the dialog shows the version the server now holds.
      void reload();
    };
    if (open === "recertify") {
      recertify.mutate(
        { entityId: entity.id, etag: entity.etag, validForDays: daysNumber },
        { onSuccess, onError },
      );
    } else if (open === "deprecate") {
      deprecate.mutate({ entityId: entity.id, etag: entity.etag }, { onSuccess, onError });
    }
  };

  return (
    <div className={styles.stack}>
      <div className={styles.row}>
        {canDeprecate ? (
          <Button
            data-testid="deprecate-open"
            onClick={(e) => {
              triggerRef.current = e.currentTarget;
              setDone("");
              setOpen("deprecate");
            }}
          >
            {S.deprecate}
          </Button>
        ) : null}
        {isOwner ? (
          <>
            <Field
              label={S.validForDays}
              hint={S.validForHint}
              validationState={daysOk ? "none" : "error"}
            >
              <Input
                type="number"
                value={days}
                min={1}
                max={730}
                onChange={(_e, d) => setDays(d.value)}
              />
            </Field>
            <Button
              data-testid="recertify-open"
              disabled={!daysOk}
              onClick={(e) => {
                triggerRef.current = e.currentTarget;
                setDone("");
                setOpen("recertify");
              }}
            >
              {S.recertify}
            </Button>
          </>
        ) : null}
      </div>
      {done === "" ? null : (
        <p role="status" data-testid="change-done">
          {done}
        </p>
      )}
      <ChangeConfirmDialog
        open={open !== null}
        title={open === "recertify" ? S.recertifyTitle : S.deprecateTitle}
        target={entity.id}
        version={entity.etag}
        diff={diff}
        submitting={mutation.isPending}
        reasonNote={S.reasonNotStored}
        error={changeError(mutation.error)}
        triggerRef={triggerRef}
        onSubmit={submit}
        onClose={close}
      />
    </div>
  );
}

function Detail({ entity }: { readonly entity: CatalogEntityView }): ReactElement {
  const neighbors = useNeighbors({ entityId: entity.id });
  const owners = ownersOf(entity, neighbors.data);
  const f = S.fields;
  return (
    <Panel compact title={entity.display_name ?? entity.id}>
      <dl>
        <dt>{f.id}</dt>
        <dd data-testid="entity-id">
          <code>{entity.id}</code>
        </dd>
        <dt>{f.type}</dt>
        <dd>{entity.entity_type}</dd>
        <dt>{f.domain}</dt>
        <dd>{entity.domain_id}</dd>
        <dt>{f.lifecycle}</dt>
        <dd data-testid="entity-lifecycle">
          <LifecyclePill value={entity.lifecycle_status} />
        </dd>
        <dt>{f.version}</dt>
        <dd data-testid="entity-version">{entity.version}</dd>
        <dt>{f.etag}</dt>
        <dd data-testid="entity-etag">
          <code>{entity.etag}</code>
        </dd>
        <dt>{f.updated}</dt>
        <dd>
          <Timestamp value={entity.updated_at} />
        </dd>
        {entity.entity_type === "owner" ? (
          <>
            <dt>{f.ownerKind}</dt>
            <dd>{entity.owner_kind ?? ""}</dd>
            <dt>{f.recertifiedAt}</dt>
            <dd>
              {entity.recertified_at === undefined || entity.recertified_at === null ? (
                S.never
              ) : (
                <Timestamp value={entity.recertified_at} />
              )}
            </dd>
            <dt>{f.recertifyBy}</dt>
            <dd data-testid="entity-recertify-by">
              {entity.recertify_by === undefined || entity.recertify_by === null ? (
                S.never
              ) : (
                <Timestamp value={entity.recertify_by} />
              )}
            </dd>
          </>
        ) : (
          <>
            <dt>{f.owners}</dt>
            <dd data-testid="entity-owners">
              {owners.length === 0
                ? S.noOwners
                : owners.map((id) => (
                    <span key={id}>
                      <EntityLink id={id} />{" "}
                    </span>
                  ))}
            </dd>
          </>
        )}
      </dl>
    </Panel>
  );
}

function EntityBody({ entityId }: { readonly entityId: string }): ReactElement {
  const styles = useStyles();
  const entity = useEntity({ entityId });
  if (entity.isError) {
    if (entity.error.status === 404)
      return <EmptyState title={S.notFound} testId="entity-not-found" />;
    return (
      <QueryProblem error={entity.error} title={S.failed} onRetry={() => void entity.refetch()} />
    );
  }
  if (entity.data === undefined) {
    return (
      <div aria-busy="true" data-testid="loading-state">
        <LoadingState label={S.loading} rows={5} />
      </div>
    );
  }
  return (
    <div className={styles.stack}>
      <Detail entity={entity.data} />
      <Actions entity={entity.data} />
      <LineageSection entity={entity.data} />
    </div>
  );
}

export function CatalogEntityPage(): ReactElement {
  const [params] = useSearchParams();
  const entityId = params.get("entity_id") ?? "";
  return (
    <PageTemplate
      title={S.title}
      description={S.description}
      actions={<Link to={`/${CATALOG_EXPLORER_ROUTE}`}>{S.back}</Link>}
    >
      {entityId === "" ? (
        <EmptyState title={S.idRequired} testId="entity-required" />
      ) : (
        <EntityBody key={entityId} entityId={entityId} />
      )}
    </PageTemplate>
  );
}
