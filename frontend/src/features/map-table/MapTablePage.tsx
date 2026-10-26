import {
  makeStyles,
  mergeClasses,
  MessageBar,
  MessageBarBody,
  tokens,
} from "@fluentui/react-components";
import {
  useCallback,
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
import {
  COLUMN_COUNT,
  GridContext,
  SectionRows,
  type GridContextValue,
  type SectionData,
} from "./MapGrid";
import { useViewport } from "./hooks";
import {
  coverageText,
  HEALTH_LABEL,
  KIND_LABEL,
  metricText,
  PROVENANCE_LABEL,
  STRINGS,
  truncationText,
} from "./strings";
import type { ViewportEdge, ViewportNode } from "./types";

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
});

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
    `${KIND_LABEL[node.kind]} ${node.label}`,
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
        <EmptyState title={STRINGS.noConnections} />
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

function MapTable({ domainId }: { readonly domainId: string }): ReactElement {
  const styles = useStyles();
  const { treatment } = useUiStyle();
  const query = useViewport(domainId, null);
  const gridRef = useRef<HTMLTableSectionElement>(null);
  const [activeKey, setActiveKey] = useState<string | null>(null);
  const [selected, setSelected] = useState<{ key: string; node: ViewportNode } | null>(null);
  const [expanded, setExpanded] = useState<ReadonlySet<string>>(new Set());
  const [sections, setSections] = useState<ReadonlyMap<string, SectionData>>(new Map());

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
    return {
      domainId,
      activeKey,
      selectedKey: selected?.key ?? null,
      expanded,
      setActive: setActiveKey,
      expand,
      collapse,
      report,
      focusRow,
      activate: (key, node) => {
        setActiveKey(key);
        setSelected({ key, node });
        if (node.kind === "cluster") {
          if (expanded.has(key)) collapse(key);
          else expand(key, node);
        }
      },
    };
  }, [domainId, activeKey, selected, expanded, report, focusRow]);

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
        <EmptyState title={STRINGS.empty} />
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

  const selectedConnections =
    selected === null
      ? 0
      : edges.filter((e) => e.source === selected.node.id || e.target === selected.node.id).length;

  return (
    <>
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
  const mapHref =
    domainId === "" ? MAP_PATH : `${MAP_PATH}?domain_id=${encodeURIComponent(domainId)}`;
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
        <MapTable key={domainId} domainId={domainId} />
      )}
    </PageTemplate>
  );
}
