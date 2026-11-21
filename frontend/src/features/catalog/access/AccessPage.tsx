import {
  Button,
  Checkbox,
  Field,
  Input,
  Select,
  makeStyles,
  tokens,
} from "@fluentui/react-components";
import { useState, type ReactElement } from "react";
import { useSelectedDomain } from "../../../app/domain";
import { EmptyState, LoadingState, PageTemplate, Panel } from "../../../design-system";
import { useEntityList } from "../explorerHooks";
import { PartialBanner, ProblemView, ResultTable, UnassessedTable } from "./AccessResults";
import { useAccessQuery, useDependents, useRegionGroups } from "./hooks";
import { ACCESS_STRINGS as S } from "./strings";
import {
  SENSITIVITY_CATEGORIES,
  type AccessDependentsResponse,
  type AccessMode,
  type AccessQueryBody,
  type AccessQueryResponse,
  type SensitivityCategoryName,
} from "./types";

const useStyles = makeStyles({
  stack: { display: "flex", flexDirection: "column", rowGap: tokens.spacingVerticalM },
  row: {
    display: "flex",
    flexWrap: "wrap",
    alignItems: "flex-end",
    columnGap: tokens.spacingHorizontalM,
    rowGap: tokens.spacingVerticalS,
  },
  grow: { minWidth: "260px", flexGrow: 1 },
});

const DEPTHS = [1, 2, 3, 4, 5] as const;

type Shown = "query" | "dependents" | null;

function WritesPanel({
  onRun,
  busy,
  includeUnassessed,
}: {
  readonly onRun: (body: AccessQueryBody) => void;
  readonly busy: boolean;
  readonly includeUnassessed: boolean;
}): ReactElement {
  const styles = useStyles();
  const Q = S.questions.writes;
  const { domainId } = useSelectedDomain();
  const list = useEntityList(
    { domain: domainId, entityType: "grounding_source", lifecycle: "" },
    true,
  );
  const [asset, setAsset] = useState("");
  const [mode, setMode] = useState<AccessMode>("write");
  const assets = list.data?.pages.flatMap((p) => p.items) ?? [];
  return (
    <Panel title={Q.title} landmark="region" testId="question-writes">
      <div className={styles.row}>
        <Field label={Q.assetLabel} className={styles.grow}>
          <Select
            value={asset}
            disabled={assets.length === 0}
            onChange={(_e, d) => setAsset(d.value)}
          >
            <option value="">{Q.assetPlaceholder}</option>
            {assets.map((a) => (
              <option key={a.id} value={a.id}>
                {a.display_name ?? a.id}
              </option>
            ))}
          </Select>
        </Field>
        <Field label={Q.modeLabel}>
          <Select value={mode} onChange={(_e, d) => setMode(d.value === "read" ? "read" : "write")}>
            <option value="write">{Q.modeWrite}</option>
            <option value="read">{Q.modeRead}</option>
          </Select>
        </Field>
        <Button
          appearance="primary"
          data-testid="run-writes"
          disabled={asset === "" || busy}
          onClick={() =>
            onRun({
              asset_ids: [asset],
              filters: {},
              modes: [mode],
              include_unassessed: includeUnassessed,
            })
          }
        >
          {busy ? S.running : S.run}
        </Button>
      </div>
      {list.isLoading ? <LoadingState label={Q.loadingAssets} rows={1} /> : null}
      {list.isError ? (
        <p role="alert">{Q.assetsFailed}</p>
      ) : domainId === "" ? (
        <p>{S.noDomain}</p>
      ) : list.isSuccess && assets.length === 0 ? (
        <p>{Q.noAssets}</p>
      ) : null}
      {list.hasNextPage ? (
        <Button
          appearance="subtle"
          disabled={list.isFetchingNextPage}
          onClick={() => void list.fetchNextPage()}
        >
          {Q.loadMore}
        </Button>
      ) : null}
    </Panel>
  );
}

function SensitivityPanel({
  onRun,
  busy,
  includeUnassessed,
}: {
  readonly onRun: (body: AccessQueryBody) => void;
  readonly busy: boolean;
  readonly includeUnassessed: boolean;
}): ReactElement {
  const styles = useStyles();
  const Q = S.questions.sensitivity;
  const [category, setCategory] = useState<SensitivityCategoryName | "">("");
  const [personal, setPersonal] = useState(false);
  const ready = category !== "" || personal;
  return (
    <Panel title={Q.title} landmark="region" testId="question-sensitivity">
      <div className={styles.row}>
        <Field label={Q.categoryLabel}>
          <Select
            value={category}
            onChange={(_e, d) => {
              const found = SENSITIVITY_CATEGORIES.find((c) => c === d.value);
              setCategory(found ?? "");
            }}
          >
            <option value="">{Q.anyCategory}</option>
            {SENSITIVITY_CATEGORIES.map((c) => (
              <option key={c} value={c}>
                {S.categoryLabels[c] ?? c}
              </option>
            ))}
          </Select>
        </Field>
        <Checkbox
          label={Q.personalData}
          checked={personal}
          onChange={(_e, d) => setPersonal(d.checked === true)}
        />
        <Button
          appearance="primary"
          data-testid="run-sensitivity"
          disabled={!ready || busy}
          onClick={() =>
            onRun({
              asset_ids: [],
              filters: {
                ...(category === "" ? {} : { sensitivity_categories: [category] }),
                ...(personal ? { contains_personal_data: true } : {}),
              },
              modes: ["read", "write"],
              include_unassessed: includeUnassessed,
            })
          }
        >
          {busy ? S.running : S.run}
        </Button>
      </div>
      <p>{ready ? Q.note : Q.needFilter}</p>
    </Panel>
  );
}

function RegionPanel({
  onRun,
  busy,
  includeUnassessed,
}: {
  readonly onRun: (body: AccessQueryBody) => void;
  readonly busy: boolean;
  readonly includeUnassessed: boolean;
}): ReactElement {
  const styles = useStyles();
  const Q = S.questions.region;
  const groups = useRegionGroups({});
  const [group, setGroup] = useState("");
  const available = groups.data?.groups ?? [];
  return (
    <Panel title={Q.title} landmark="region" testId="question-region">
      <div className={styles.row}>
        <Field label={Q.groupLabel} className={styles.grow}>
          <Select
            value={group}
            disabled={available.length === 0}
            onChange={(_e, d) => setGroup(d.value)}
          >
            <option value="">{Q.choose}</option>
            {available.map((g) => (
              <option key={g.name} value={g.name}>
                {`${S.groupLabels[g.name] ?? g.name} (${Q.members(g.regions.length)})`}
              </option>
            ))}
          </Select>
        </Field>
        <Button
          appearance="primary"
          data-testid="run-region"
          disabled={group === "" || busy}
          onClick={() =>
            onRun({
              asset_ids: [],
              filters: { region_group: group },
              modes: ["read", "write"],
              include_unassessed: includeUnassessed,
            })
          }
        >
          {busy ? S.running : S.run}
        </Button>
      </div>
      {groups.isLoading ? <LoadingState label={Q.loadingGroups} rows={1} /> : null}
      {groups.isError ? <p role="alert">{Q.groupsFailed}</p> : null}
      {groups.isSuccess && available.length === 0 ? <p>{Q.noGroups}</p> : null}
      <p>{Q.note}</p>
    </Panel>
  );
}

function DependentsPanel({
  onRun,
  busy,
}: {
  readonly onRun: (nodeId: string, depth: number) => void;
  readonly busy: boolean;
}): ReactElement {
  const styles = useStyles();
  const Q = S.dependents;
  const [node, setNode] = useState("");
  const [depth, setDepth] = useState(3);
  const trimmed = node.trim();
  return (
    <Panel title={Q.title} landmark="region" testId="question-dependents">
      <div className={styles.row}>
        <Field label={Q.nodeLabel} hint={Q.nodeHint} className={styles.grow}>
          <Input value={node} onChange={(_e, d) => setNode(d.value)} />
        </Field>
        <Field label={Q.depthLabel}>
          <Select value={String(depth)} onChange={(_e, d) => setDepth(Number(d.value))}>
            {DEPTHS.map((n) => (
              <option key={n} value={String(n)}>
                {Q.depthOption(n)}
              </option>
            ))}
          </Select>
        </Field>
        <Button
          appearance="primary"
          data-testid="run-dependents"
          disabled={trimmed === "" || busy}
          onClick={() => onRun(trimmed, depth)}
        >
          {busy ? S.running : S.run}
        </Button>
      </div>
      {trimmed === "" ? <p>{Q.needNode}</p> : null}
    </Panel>
  );
}

function QueryResults({ data }: { readonly data: AccessQueryResponse }): ReactElement {
  const R = S.results;
  const unassessed = data.unassessed_assets ?? [];
  return (
    <>
      {data.truncated ? (
        <PartialBanner reason={data.truncated_reason} scanned={data.assets_scanned} />
      ) : null}
      <p data-testid="result-summary">
        {R.summary(data.rows.length, data.assets.length)}. {R.scanned(data.assets_scanned)}.
      </p>
      {data.rows.length === 0 ? (
        <EmptyState title={R.empty} testId="access-empty" />
      ) : (
        <ResultTable rows={data.rows} label={R.tableLabel} variant="access" />
      )}
      {unassessed.length > 0 ? (
        <Panel title={R.unassessedTitle} level={3} testId="unassessed-section">
          <p>
            {R.unassessedCount(data.unassessed_count ?? unassessed.length)}. {R.unassessedNote}
          </p>
          <UnassessedTable assets={unassessed} />
        </Panel>
      ) : null}
    </>
  );
}

function DependentsResults({ data }: { readonly data: AccessDependentsResponse }): ReactElement {
  const R = S.results;
  return (
    <>
      {data.truncated ? (
        <PartialBanner reason={data.truncated_reason} scanned={data.assets_scanned} />
      ) : null}
      <p data-testid="result-summary">
        {S.dependents.total(data.total)}. {R.scanned(data.assets_scanned)}.
      </p>
      {data.groups.length === 0 || data.total === 0 ? (
        <EmptyState title={R.emptyDependents} testId="access-empty" />
      ) : (
        data.groups.map((g) => (
          <Panel
            key={g.depth}
            level={3}
            title={S.dependents.groupTitle(g.depth, g.rows.length)}
            testId="depth-group"
          >
            <ResultTable
              rows={g.rows}
              label={S.dependents.groupTitle(g.depth, g.rows.length)}
              variant="dependents"
            />
          </Panel>
        ))
      )}
    </>
  );
}

export function AccessPage(): ReactElement {
  const styles = useStyles();
  const query = useAccessQuery();
  const dependents = useDependents();
  const [includeUnassessed, setIncludeUnassessed] = useState(false);
  const [shown, setShown] = useState<Shown>(null);
  const busy = query.isPending || dependents.isPending;

  const [retry, setRetry] = useState<() => void>(() => () => undefined);

  const runQuery = (body: AccessQueryBody): void => {
    dependents.reset();
    setShown("query");
    setRetry(() => () => query.mutate(body));
    query.mutate(body);
  };
  const runDependents = (nodeId: string, maxDepth: number): void => {
    query.reset();
    setShown("dependents");
    setRetry(() => () => dependents.mutate({ nodeId, maxDepth }));
    dependents.mutate({ nodeId, maxDepth });
  };

  return (
    <PageTemplate title={S.title} description={S.description}>
      <div className={styles.stack}>
        <p>{S.observedNote}</p>
        <Checkbox
          label={S.options.includeUnassessed}
          checked={includeUnassessed}
          onChange={(_e, d) => setIncludeUnassessed(d.checked === true)}
        />
        <p>{S.options.includeUnassessedHint}</p>
        <WritesPanel onRun={runQuery} busy={busy} includeUnassessed={includeUnassessed} />
        <SensitivityPanel onRun={runQuery} busy={busy} includeUnassessed={includeUnassessed} />
        <RegionPanel onRun={runQuery} busy={busy} includeUnassessed={includeUnassessed} />
        <DependentsPanel onRun={runDependents} busy={busy} />
        {shown === null ? null : (
          <Panel title={S.results.title} landmark="region" testId="access-results">
            {shown === "query" ? (
              query.isPending ? (
                <LoadingState label={S.results.loading} />
              ) : query.isError ? (
                <ProblemView error={query.error} onRetry={retry} />
              ) : query.data === undefined ? null : (
                <QueryResults data={query.data} />
              )
            ) : dependents.isPending ? (
              <LoadingState label={S.results.loading} />
            ) : dependents.isError ? (
              <ProblemView error={dependents.error} onRetry={retry} />
            ) : dependents.data === undefined ? null : (
              <DependentsResults data={dependents.data} />
            )}
          </Panel>
        )}
      </div>
    </PageTemplate>
  );
}
