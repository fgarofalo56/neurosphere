import {
  Button,
  Dropdown,
  Field,
  Input,
  Option,
  makeStyles,
  tokens,
} from "@fluentui/react-components";
import { useState, type ReactElement } from "react";
import { ForbiddenError, useApiClient } from "../../api/index.js";
import { useSelectedDomain } from "../../app/domain";
import {
  DataTable,
  EmptyState,
  LoadingState,
  PageTemplate,
  Panel,
  Timestamp,
} from "../../design-system";
import { fetchExportPage, useEntityList, useEntitySearch } from "./explorerHooks";
import { EntityLink, LifecyclePill, QueryProblem, downloadJson } from "./explorerParts";
import { EXPLORER_STRINGS } from "./explorerStrings";
import {
  ENTITY_TYPES,
  LIFECYCLES,
  type CatalogEntityView,
  type EntityTypeName,
  type LifecycleName,
} from "./explorerTypes";

const S = EXPLORER_STRINGS.explorer;

const useStyles = makeStyles({
  stack: { display: "flex", flexDirection: "column", rowGap: tokens.spacingVerticalM },
  row: {
    display: "flex",
    flexWrap: "wrap",
    alignItems: "flex-end",
    columnGap: tokens.spacingHorizontalM,
    rowGap: tokens.spacingVerticalS,
  },
  dropdown: { minWidth: "180px" },
});

const ANY = "";

function EntityRows({ rows }: { readonly rows: readonly CatalogEntityView[] }): ReactElement {
  return (
    <DataTable
      label={S.title}
      rows={rows}
      getRowId={(e) => e.id}
      getRowProps={(e) => ({ "data-testid": "entity-row", "data-entity": e.id })}
      columns={[
        {
          key: "name",
          header: S.table.name,
          render: (e) => <EntityLink id={e.id}>{e.display_name ?? e.id}</EntityLink>,
        },
        { key: "id", header: S.table.id, render: (e) => <code>{e.id}</code> },
        { key: "type", header: S.table.type, render: (e) => e.entity_type },
        {
          key: "lifecycle",
          header: S.table.lifecycle,
          render: (e) => <LifecyclePill value={e.lifecycle_status} />,
        },
        {
          key: "updated",
          header: S.table.updated,
          render: (e) => <Timestamp value={e.updated_at} />,
        },
      ]}
    />
  );
}

function TypeFilter(props: {
  readonly value: EntityTypeName | "";
  readonly onChange: (v: EntityTypeName | "") => void;
}): ReactElement {
  const styles = useStyles();
  return (
    <Field label={S.typeLabel}>
      <Dropdown
        className={styles.dropdown}
        value={props.value === "" ? S.anyOption : props.value}
        selectedOptions={[props.value]}
        onOptionSelect={(_e, d) => props.onChange((d.optionValue ?? ANY) as EntityTypeName | "")}
      >
        <Option value={ANY}>{S.anyOption}</Option>
        {ENTITY_TYPES.map((t) => (
          <Option key={t} value={t}>
            {t}
          </Option>
        ))}
      </Dropdown>
    </Field>
  );
}

function LifecycleFilter(props: {
  readonly value: LifecycleName | "";
  readonly onChange: (v: LifecycleName | "") => void;
}): ReactElement {
  const styles = useStyles();
  return (
    <Field label={S.lifecycleLabel}>
      <Dropdown
        className={styles.dropdown}
        value={props.value === "" ? S.anyOption : props.value}
        selectedOptions={[props.value]}
        onOptionSelect={(_e, d) => props.onChange((d.optionValue ?? ANY) as LifecycleName | "")}
      >
        <Option value={ANY}>{S.anyOption}</Option>
        {LIFECYCLES.map((t) => (
          <Option key={t} value={t}>
            {t}
          </Option>
        ))}
      </Dropdown>
    </Field>
  );
}

interface ExportState {
  readonly page: number;
  readonly cursor: string | undefined;
  readonly message: string;
  readonly failed: boolean;
}

function ExportControl(props: {
  readonly domain: string;
  readonly entityType: EntityTypeName | "";
  readonly lifecycle: LifecycleName | "";
}): ReactElement {
  const client = useApiClient();
  const [state, setState] = useState<ExportState>({
    page: 0,
    cursor: undefined,
    message: "",
    failed: false,
  });
  const [busy, setBusy] = useState(false);
  const more = state.page > 0 && state.cursor !== undefined;
  const run = (): void => {
    setBusy(true);
    fetchExportPage(client, {
      domain: props.domain,
      entityType: props.entityType,
      lifecycle: props.lifecycle,
      cursor: more ? state.cursor : undefined,
    })
      .then((page) => {
        const n = more ? state.page + 1 : 1;
        downloadJson(`catalog-export-page-${String(n)}.json`, page);
        setState({
          page: n,
          cursor: page.next_cursor ?? undefined,
          message: S.exportDone(n, page.items.length),
          failed: false,
        });
      })
      .catch((error: unknown) => {
        setState({
          page: 0,
          cursor: undefined,
          message: error instanceof ForbiddenError ? S.exportForbidden : S.exportFailed,
          failed: true,
        });
      })
      .finally(() => setBusy(false));
  };
  return (
    <div>
      <Button data-testid="export-json" disabled={busy} onClick={run}>
        {more ? S.exportNext : S.export}
      </Button>
      {state.message === "" ? null : (
        <p role={state.failed ? "alert" : "status"} data-testid="export-message">
          {state.message} {more ? S.exportMore : ""}
        </p>
      )}
    </div>
  );
}

function ListBody(props: {
  readonly domain: string;
  readonly type: EntityTypeName | "";
  readonly lifecycle: LifecycleName | "";
}): ReactElement {
  const list = useEntityList(
    { domain: props.domain, entityType: props.type, lifecycle: props.lifecycle },
    true,
  );
  if (list.isError) {
    return <QueryProblem error={list.error} title={S.failed} onRetry={() => void list.refetch()} />;
  }
  if (list.data === undefined) {
    return (
      <div aria-busy="true" data-testid="loading-state">
        <LoadingState label={S.loading} rows={5} />
      </div>
    );
  }
  const rows = list.data.pages.flatMap((p) => p.items);
  const more = list.hasNextPage;
  if (rows.length === 0 && !more) return <EmptyState title={S.empty} testId="empty-state" />;
  return (
    <>
      <p data-testid="entity-count">{S.count(rows.length, more)}</p>
      <EntityRows rows={rows} />
      {more ? (
        <Button
          data-testid="load-more"
          disabled={list.isFetchingNextPage}
          onClick={() => void list.fetchNextPage()}
        >
          {S.loadMore}
        </Button>
      ) : null}
    </>
  );
}

function SearchBody(props: {
  readonly domain: string;
  readonly term: string;
  readonly type: EntityTypeName | "";
  readonly lifecycle: LifecycleName | "";
}): ReactElement {
  const search = useEntitySearch({
    domain: props.domain,
    term: props.term,
    entityType: props.type,
  });
  if (search.isError) {
    return (
      <QueryProblem error={search.error} title={S.failed} onRetry={() => void search.refetch()} />
    );
  }
  if (search.data === undefined) {
    return (
      <div aria-busy="true" data-testid="loading-state">
        <LoadingState label={S.loading} rows={5} />
      </div>
    );
  }
  const rows = search.data.nodes.filter(
    (n) => props.lifecycle === "" || n.lifecycle_status === props.lifecycle,
  );
  if (rows.length === 0 && !search.data.truncated) {
    return <EmptyState title={S.empty} testId="empty-state" />;
  }
  return (
    <>
      <p data-testid="entity-count">{S.count(rows.length, search.data.truncated)}</p>
      {search.data.truncated ? <p data-testid="search-truncated">{S.searchTruncated}</p> : null}
      <EntityRows rows={rows} />
    </>
  );
}

export function CatalogExplorerPage(): ReactElement {
  const styles = useStyles();
  const { domainId, domains } = useSelectedDomain();
  const [draft, setDraft] = useState("");
  const [term, setTerm] = useState("");
  const [type, setType] = useState<EntityTypeName | "">("");
  const [lifecycle, setLifecycle] = useState<LifecycleName | "">("");
  const canExport =
    domains.find((d) => d.domain_id === domainId)?.permissions.includes("data.export") === true;

  return (
    <PageTemplate title={S.title} description={EXPLORER_STRINGS.explorer.description}>
      <div className={styles.stack}>
        <Panel compact>
          <div className={styles.row}>
            <Field label={S.searchLabel}>
              <Input
                value={draft}
                placeholder={S.searchPlaceholder}
                maxLength={256}
                onChange={(_e, d) => setDraft(d.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") setTerm(draft.trim());
                }}
              />
            </Field>
            <Button
              appearance="primary"
              data-testid="search-submit"
              onClick={() => setTerm(draft.trim())}
            >
              {S.searchButton}
            </Button>
            {term === "" ? null : (
              <Button
                data-testid="search-clear"
                onClick={() => {
                  setDraft("");
                  setTerm("");
                }}
              >
                {S.clear}
              </Button>
            )}
            <TypeFilter value={type} onChange={setType} />
            <LifecycleFilter value={lifecycle} onChange={setLifecycle} />
            {canExport ? (
              <ExportControl domain={domainId} entityType={type} lifecycle={lifecycle} />
            ) : null}
          </div>
          {term === "" ? null : <p data-testid="search-note">{S.searchNote}</p>}
        </Panel>
        {domainId === "" ? (
          <EmptyState title={S.noDomain} testId="no-domain" />
        ) : term === "" ? (
          <ListBody domain={domainId} type={type} lifecycle={lifecycle} />
        ) : (
          <SearchBody domain={domainId} term={term} type={type} lifecycle={lifecycle} />
        )}
      </div>
    </PageTemplate>
  );
}
