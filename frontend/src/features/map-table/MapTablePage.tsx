import {
  Button,
  Field,
  makeStyles,
  mergeClasses,
  MessageBar,
  MessageBarBody,
  Select,
  tokens,
} from "@fluentui/react-components";
import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type KeyboardEvent,
  type ReactElement,
} from "react";
import { Link } from "react-router";
import { useSelectedDomain } from "../../app/domain";
import {
  DataTable,
  EmptyState,
  ErrorState as StyledErrorState,
  LoadingState,
  PageTemplate,
  StatusPill,
  useUiStyle,
  type DataTableColumn,
  type StatusTone,
} from "../../design-system";
import { ForbiddenError, UnauthorizedError, type ApiError } from "../../api/index.js";
import { MAP_PATH } from "../map/paths";
import { ForbiddenState } from "../workspaces/ForbiddenState";
import { FilterBar } from "../map/filters/FilterBar";
import { useMapFilters, type MapFilterQuery } from "../map/filters/useMapFilters";
import {
  DEFAULT_IMPACT_DEPTH,
  MAX_IMPACT_DEPTH,
  MIN_IMPACT_DEPTH,
  deriveImpact,
  useMapImpact,
} from "../map/impact";
import { SearchBox } from "../map/search/SearchBox";
import {
  COLUMN_COUNT,
  GridContext,
  rowKeyOf,
  SectionRows,
  type GridContextValue,
  type ImpactView,
  type SectionData,
} from "./MapGrid";
import { NoDataEmptyState } from "../source-status";
import { useViewport } from "./hooks";
import {
  coverageText,
  HEALTH_LABEL,
  kindLabel,
  metricText,
  PROVENANCE_LABEL,
  STRINGS,
  truncationText,
} from "./strings";
import type { SearchMatch, ViewportEdge, ViewportNode } from "./types";

const useStyles = makeStyles({
  table: { borderCollapse: "collapse", width: "100%" },
  caption: { textAlign: "left", padding: tokens.spacingVerticalS, fontWeight: 600 },
  th: {
    textAlign: "left",
    padding: `${tokens.spacingVerticalXS} ${tokens.spacingHorizontalS}`,
    borderBottom: `2px solid ${tokens.colorNeutralStroke1}`,
    color: tokens.colorNeutralForeground2,
    fontWeight: tokens.fontWeightSemibold,
  },
  upper: { textTransform: "uppercase", letterSpacing: "0.06em", fontSize: tokens.fontSizeBase200 },
  cell: {
    padding: `${tokens.spacingVerticalXS} ${tokens.spacingHorizontalS}`,
    borderBottom: `1px solid ${tokens.colorNeutralStroke2}`,
  },
  detail: {
    marginTop: tokens.spacingVerticalM,
    padding: tokens.spacingVerticalM,
    border: `1px solid ${tokens.colorNeutralStroke2}`,
    borderRadius: tokens.borderRadiusMedium,
    backgroundColor: tokens.colorNeutralBackground1,
  },
  link: {
    color: tokens.colorBrandForegroundLink,
    textDecorationLine: "none",
    fontWeight: tokens.fontWeightSemibold,
    ":hover": { textDecorationLine: "underline" },
  },
  gap: { marginTop: tokens.spacingVerticalL },
  controls: {
    display: "flex",
    flexWrap: "wrap",
    alignItems: "flex-end",
    columnGap: tokens.spacingHorizontalL,
    rowGap: tokens.spacingVerticalS,
    marginBottom: tokens.spacingVerticalM,
  },
  note: { color: tokens.colorNeutralForeground2, fontSize: tokens.fontSizeBase200 },
});

/** A search result chosen in the search box; the table focuses its row. */
interface SearchTarget {
  readonly match: SearchMatch;
  readonly nonce: number;
  /** The filters the choice was made under: a target for other filters is stale. */
  readonly signature: string;
}

interface PendingFocus {
  readonly id: string;
  readonly label: string;
  readonly clusterId: string;
}

function ErrorState({ error }: { readonly error: ApiError }): ReactElement {
  if (error instanceof ForbiddenError) {
    return <ForbiddenState workspace="Map" correlationId={error.correlationId} />;
  }
  const ref = error.correlationId !== "" ? ` (reference ${error.correlationId})` : "";
  const text =
    error instanceof UnauthorizedError
      ? "Your session is not signed in or has expired. Sign in again to view the map."
      : "The request failed or the service is unavailable. This is not an empty result.";
  return (
    <div data-testid="error-state">
      <StyledErrorState title="Could not load the map" message={`${text}${ref}`} />
    </div>
  );
}

function nodeSummary(node: ViewportNode, connections: number): string {
  const m = node.metrics;
  const parts = [
    `${kindLabel(node.kind)} ${node.label}`,
    `health ${HEALTH_LABEL[m.health]}`,
    `tokens ${metricText(m.tokens)}`,
    `context size ${metricText(m.context_size)}`,
    `frequency ${metricText(m.frequency)}`,
    `latency p95 ${metricText(m.latency_p95_ms, " ms")}`,
    `${connections} loaded ${connections === 1 ? "connection" : "connections"}`,
  ];
  if (node.kind === "cluster") parts.splice(1, 0, `members ${metricText(node.member_count)}`);
  return parts.join(", ");
}

const PROVENANCE_TONE: Readonly<Record<ViewportEdge["provenance"], StatusTone>> = {
  observed: "neutral",
  declared: "neutral",
  inferred: "warning",
};

function ConnectionsTable({
  edges,
  labels,
}: {
  readonly edges: readonly ViewportEdge[];
  readonly labels: ReadonlyMap<string, string>;
}): ReactElement {
  if (edges.length === 0) {
    return (
      <div data-testid="no-connections">
        <NoDataEmptyState what={STRINGS.noConnections} sources={["foundry", "apim_gateway"]} />
      </div>
    );
  }
  const columns: readonly DataTableColumn<ViewportEdge>[] = [
    {
      key: "source",
      header: STRINGS.connections.source,
      render: (e) => labels.get(e.source) ?? e.source,
    },
    {
      key: "target",
      header: STRINGS.connections.target,
      render: (e) => labels.get(e.target) ?? e.target,
    },
    {
      key: "provenance",
      header: STRINGS.connections.provenance,
      render: (e) => (
        <span data-provenance={e.provenance}>
          <StatusPill label={PROVENANCE_LABEL[e.provenance]} tone={PROVENANCE_TONE[e.provenance]} />
        </span>
      ),
    },
  ];
  return (
    <div data-testid="connections-table">
      <DataTable
        label={STRINGS.connectionsCaption}
        columns={columns}
        rows={edges}
        getRowId={(e) => e.id}
      />
    </div>
  );
}

interface MapTableProps {
  readonly domainId: string;
  readonly filters: MapFilterQuery;
  /** The filters' signature; a search target made under other filters is ignored. */
  readonly signature: string;
  readonly target: SearchTarget | null;
}

function MapTable({ domainId, filters, signature, target }: MapTableProps): ReactElement {
  const styles = useStyles();
  const { treatment } = useUiStyle();
  const query = useViewport(domainId, null, filters);
  const gridRef = useRef<HTMLTableSectionElement>(null);
  const [activeKey, setActiveKey] = useState<string | null>(null);
  const [selected, setSelected] = useState<{ key: string; node: ViewportNode } | null>(null);
  const [expanded, setExpanded] = useState<ReadonlySet<string>>(new Set());
  const [sections, setSections] = useState<ReadonlyMap<string, SectionData>>(new Map());
  const [impactRoot, setImpactRoot] = useState<{ id: string; label: string } | null>(null);
  const [depth, setDepth] = useState(DEFAULT_IMPACT_DEPTH);
  const [searchNote, setSearchNote] = useState("");
  const [pending, setPending] = useState<PendingFocus | null>(null);
  const handledNonce = useRef(0);

  const impactQuery = useMapImpact(domainId, impactRoot?.id ?? null, depth);
  const impactState = useMemo(() => {
    if (impactRoot === null || impactQuery.data === undefined) return null;
    if (impactQuery.data.node_id !== impactRoot.id) return null; // a previous node's answer
    const loaded = new Set<string>();
    for (const s of sections.values()) for (const n of s.nodes) loaded.add(n.id);
    return deriveImpact(impactQuery.data, {
      hasNode: (id) => loaded.has(id),
      hasEdge: () => false,
    });
  }, [impactRoot, impactQuery.data, sections]);
  const impactView = useMemo<ImpactView | null>(() => {
    if (impactRoot === null) return null;
    const depthById = new Map<string, number>();
    for (const level of impactState?.levels ?? []) {
      for (const row of level.rows) depthById.set(row.id, row.depth);
    }
    return { rootId: impactRoot.id, depthById };
  }, [impactRoot, impactState]);

  const report = useCallback((section: string, data: SectionData | null) => {
    setSections((prev) => {
      const next = new Map(prev);
      if (data === null) next.delete(section);
      else next.set(section, data);
      return next;
    });
  }, []);

  const focusRow = useCallback((key: string): boolean => {
    const rows = gridRef.current?.querySelectorAll<HTMLElement>("tr[data-row-key]");
    for (const row of rows ?? []) {
      if (row.dataset["rowKey"] === key) {
        row.focus();
        return true;
      }
    }
    return false;
  }, []);

  const focusInGrid = useCallback((): boolean => {
    const active = document.activeElement;
    return (
      active === null || active === document.body || gridRef.current?.contains(active) === true
    );
  }, []);

  // A stale active key (its row was collapsed away) must not leave the grid with no tabbable row.
  const liveActiveKey = useMemo(() => {
    if (activeKey === null) return null;
    for (const [section, data] of sections) {
      if (data.nodes.some((n) => rowKeyOf(section, n) === activeKey)) return activeKey;
    }
    return null;
  }, [activeKey, sections]);

  const ctx = useMemo<GridContextValue>(() => {
    const expand = (key: string, node: ViewportNode): void => {
      setExpanded((prev) => new Set(prev).add(key));
      setSelected({ key, node });
    };
    const collapse = (key: string): void => {
      setExpanded((prev) => {
        const next = new Set(prev);
        next.delete(key);
        return next;
      });
      setActiveKey(key);
    };
    const toggleImpact = (key: string, node: ViewportNode): void => {
      if (node.kind === "cluster") return;
      setSelected({ key, node });
      setImpactRoot((prev) => (prev?.id === node.id ? null : { id: node.id, label: node.label }));
    };
    return {
      domainId,
      filters,
      impact: impactView,
      columnCount: impactView === null ? COLUMN_COUNT : COLUMN_COUNT + 1,
      toggleImpact,
      activeKey: liveActiveKey,
      selectedKey: selected?.key ?? null,
      expanded,
      setActive: setActiveKey,
      expand,
      collapse,
      report,
      focusRow,
      focusInGrid,
      activate: (key, node) => {
        setActiveKey(key);
        setSelected({ key, node });
        if (node.kind === "cluster") {
          if (expanded.has(key)) collapse(key);
          else expand(key, node);
        }
      },
    };
  }, [
    domainId,
    filters,
    impactView,
    activeKey,
    liveActiveKey,
    selected,
    expanded,
    report,
    focusRow,
    focusInGrid,
  ]);

  // A search result chosen in the search box: take it once.
  useEffect(() => {
    if (target === null || target.signature !== signature) return;
    if (target.nonce === handledNonce.current) return;
    handledNonce.current = target.nonce;
    setSearchNote("");
    setPending({
      id: target.match.node.id,
      label: target.match.node.label,
      clusterId: target.match.cluster_id,
    });
  }, [target, signature]);

  // Focus the searched row. A row inside a collapsed cluster opens the cluster first; a row that
  // is not on a loaded page is said in text (the table pages clusters, it has no neighbourhood
  // fetch), never silently dropped.
  useEffect(() => {
    if (pending === null || query.isPending) return;
    let found: { key: string; node: ViewportNode } | null = null;
    for (const [section, data] of sections) {
      const node = data.nodes.find((n) => n.id === pending.id);
      if (node !== undefined) {
        found = { key: rowKeyOf(section, node), node };
        break;
      }
    }
    if (found !== null) {
      if (impactRoot !== null && impactView?.depthById.has(pending.id) !== true) {
        // The impact filter hides this row: searching is explicit navigation, so leave impact.
        if (impactRoot.id !== pending.id) {
          setImpactRoot(null);
          return;
        }
      }
      if (focusRow(found.key)) {
        setActiveKey(found.key);
        setSelected(found);
        setSearchNote(STRINGS.search.focused(pending.label));
        setPending(null);
      }
      return;
    }
    const cluster = sections.get("root")?.nodes.find((n) => n.id === pending.clusterId);
    if (cluster === undefined) {
      setSearchNote(STRINGS.search.notInTable(pending.label));
      setPending(null);
      return;
    }
    const clusterKey = rowKeyOf("root", cluster);
    if (!expanded.has(clusterKey)) {
      setExpanded((prev) => new Set(prev).add(clusterKey));
      setSearchNote(STRINGS.search.clusterOpened(cluster.label));
      return;
    }
    const section = sections.get(clusterKey);
    if (section === undefined) return; // still loading
    setSearchNote(
      section.hasNextPage
        ? STRINGS.search.notLoaded(pending.label, cluster.label)
        : STRINGS.search.notInTable(pending.label),
    );
    setPending(null);
  }, [pending, query.isPending, sections, expanded, impactRoot, impactView, focusRow]);

  const edges = useMemo(() => {
    const seen = new Map<string, ViewportEdge>();
    for (const s of sections.values()) for (const e of s.edges) seen.set(e.id, e);
    return [...seen.values()];
  }, [sections]);
  const labels = useMemo(() => {
    const map = new Map<string, string>();
    for (const s of sections.values()) for (const n of s.nodes) map.set(n.id, n.label);
    return map;
  }, [sections]);

  if (query.isError) return <ErrorState error={query.error} />;
  if (query.isPending) {
    return (
      <div aria-busy="true" data-testid="map-table-loading">
        <LoadingState label={STRINGS.loading} rows={6} />
      </div>
    );
  }

  const pages = query.data.pages;
  const last = pages[pages.length - 1];
  const hasNodes = pages.some((p) => p.nodes.length > 0);
  if (last === undefined || !hasNodes) {
    return (
      <div data-testid="empty-state">
        <NoDataEmptyState what={STRINGS.empty} sources={["foundry", "apim_gateway"]} />
      </div>
    );
  }

  const onGridKeyDown = (e: KeyboardEvent<HTMLTableSectionElement>): void => {
    const row = (e.target as HTMLElement).closest<HTMLElement>("tr[data-row-key]");
    if (row === null || row !== e.target) return;
    if (!["ArrowDown", "ArrowUp", "Home", "End"].includes(e.key)) return;
    const rows = Array.from(
      gridRef.current?.querySelectorAll<HTMLElement>("tr[data-row-key]") ?? [],
    );
    const i = rows.indexOf(row);
    const target =
      e.key === "ArrowDown"
        ? rows[Math.min(i + 1, rows.length - 1)]
        : e.key === "ArrowUp"
          ? rows[Math.max(i - 1, 0)]
          : e.key === "Home"
            ? rows[0]
            : rows[rows.length - 1];
    e.preventDefault();
    target?.focus();
  };

  const toggleImpactFor = (sel: { key: string; node: ViewportNode }): void =>
    ctx.toggleImpact(sel.key, sel.node);

  const selectedConnections =
    selected === null
      ? 0
      : edges.filter((e) => e.source === selected.node.id || e.target === selected.node.id).length;

  const canImpact = selected !== null && selected.node.kind !== "cluster";
  let impactText = "";
  if (impactRoot !== null) {
    if (impactQuery.isError) impactText = STRINGS.impact.failed;
    else if (impactState === null) impactText = STRINGS.impact.loading;
    else impactText = STRINGS.impact.affected(impactState.total, impactRoot.label);
  }
  const offscreen = impactState?.offscreen ?? [];

  return (
    <>
      <div className={styles.controls} role="group" aria-label={STRINGS.impact.heading}>
        <Button
          appearance={impactRoot === null ? "primary" : "secondary"}
          disabled={impactRoot === null && !canImpact}
          onClick={() => {
            if (impactRoot !== null) setImpactRoot(null);
            else if (selected !== null) toggleImpactFor(selected);
          }}
          data-testid="show-impact"
        >
          {impactRoot === null ? STRINGS.impact.toggle : STRINGS.impact.clear}
        </Button>
        {impactRoot !== null ? (
          <Field label={STRINGS.impact.depthLabel}>
            <Select
              value={String(depth)}
              onChange={(_, data) => setDepth(Number(data.value))}
              data-testid="impact-depth"
            >
              {Array.from({ length: MAX_IMPACT_DEPTH - MIN_IMPACT_DEPTH + 1 }, (_, i) => (
                <option key={i} value={String(MIN_IMPACT_DEPTH + i)}>
                  {MIN_IMPACT_DEPTH + i}
                </option>
              ))}
            </Select>
          </Field>
        ) : null}
        <span className={styles.note}>
          {selected !== null && selected.node.kind === "cluster"
            ? STRINGS.impact.clusterHint
            : STRINGS.impact.shortcutNote}
        </span>
      </div>
      <div role="status" aria-live="polite" aria-atomic="true" data-testid="impact-status">
        {impactText}
        {impactState?.truncated === true ? ` ${STRINGS.impact.truncated}` : ""}
      </div>
      {offscreen.length > 0 ? (
        <p className={styles.note} data-testid="impact-not-loaded">
          {STRINGS.impact.notLoaded(offscreen.length, offscreen.map((r) => r.label).join(", "))}
        </p>
      ) : null}
      <div
        className={styles.note}
        role="status"
        aria-live="polite"
        aria-atomic="true"
        data-testid="search-note"
      >
        {searchNote}
      </div>
      {last.truncated ? (
        <MessageBar intent="warning" data-testid="truncation-banner">
          <MessageBarBody>{truncationText(last.truncation_reason)}</MessageBarBody>
        </MessageBar>
      ) : null}
      <GridContext.Provider value={ctx}>
        <table
          className={styles.table}
          role="treegrid"
          aria-label={STRINGS.caption}
          data-testid="map-grid"
        >
          <caption className={styles.caption}>
            {STRINGS.caption}. <span data-testid="coverage">{coverageText(last.coverage)}</span>
          </caption>
          <thead>
            <tr>
              {Object.values(STRINGS.columns).map((c) => (
                <th
                  key={c}
                  scope="col"
                  className={mergeClasses(styles.th, treatment.uppercaseLabels && styles.upper)}
                >
                  {c}
                </th>
              ))}
              {impactRoot !== null ? (
                <th
                  scope="col"
                  className={mergeClasses(styles.th, treatment.uppercaseLabels && styles.upper)}
                >
                  {STRINGS.depthColumn}
                </th>
              ) : null}
            </tr>
          </thead>
          <tbody ref={gridRef} onKeyDown={onGridKeyDown}>
            <SectionRows
              query={query}
              section="root"
              depth={0}
              parentLabel="the map"
              showStatus={false}
            />
          </tbody>
          <tfoot>
            <tr>
              <td colSpan={COLUMN_COUNT} className={styles.cell}>
                {STRINGS.keyboardHelp}
              </td>
            </tr>
          </tfoot>
        </table>
      </GridContext.Provider>
      <div
        className={styles.detail}
        role="status"
        aria-live="polite"
        aria-atomic="true"
        data-testid="detail"
      >
        <strong>{STRINGS.detailHeading}: </strong>
        {selected === null
          ? STRINGS.nothingSelected
          : nodeSummary(selected.node, selectedConnections)}
      </div>
      <div className={styles.gap}>
        <ConnectionsTable edges={edges} labels={labels} />
      </div>
    </>
  );
}

export function MapTablePage(): ReactElement {
  const styles = useStyles();
  const { domainId } = useSelectedDomain();
  // Same URL state as the map: a filtered map URL opened here shows the same filters.
  const filters = useMapFilters();
  const [target, setTarget] = useState<SearchTarget | null>(null);
  const nonce = useRef(0);
  const query = filters.toQuery();
  const viewKey = `${domainId}|${filters.signature}`;
  const mapParams = new URLSearchParams(domainId === "" ? "" : { domain_id: domainId });
  for (const [key, value] of Object.entries(query)) mapParams.set(key, value);
  const mapHref = mapParams.size === 0 ? MAP_PATH : `${MAP_PATH}?${mapParams.toString()}`;
  return (
    <PageTemplate title={STRINGS.title} description={STRINGS.intro}>
      <p>
        <Link to={mapHref} className={styles.link}>
          {STRINGS.viewAsMap}
        </Link>
      </p>
      {domainId === "" ? (
        <div data-testid="domain-required">
          <EmptyState title={STRINGS.domainRequired} />
        </div>
      ) : (
        <>
          <div className={styles.controls}>
            <FilterBar domainId={domainId} state={filters} />
            <SearchBox
              domainId={domainId}
              onSelect={(match) => {
                nonce.current += 1;
                setTarget({ match, nonce: nonce.current, signature: viewKey });
              }}
            />
          </div>
          <MapTable
            key={viewKey}
            domainId={domainId}
            filters={query}
            signature={viewKey}
            target={target}
          />
        </>
      )}
    </PageTemplate>
  );
}
