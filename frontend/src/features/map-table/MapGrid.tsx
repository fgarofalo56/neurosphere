import { makeStyles, mergeClasses, tokens } from "@fluentui/react-components";
import type { InfiniteData, UseInfiniteQueryResult } from "@tanstack/react-query";
import {
  createContext,
  useContext,
  useEffect,
  useLayoutEffect,
  useState,
  type KeyboardEvent,
  type ReactElement,
} from "react";
import type { ApiError } from "../../api/index.js";
import { HealthIndicator, LoadingState } from "../../design-system";
import { useViewport } from "./hooks";
import { KindIcon } from "./icons";
import {
  coverageText,
  HEALTH_LABEL,
  KIND_LABEL,
  membersText,
  metricText,
  STRINGS,
  truncationText,
} from "./strings";
import type { ViewportEdge, ViewportNode, ViewportResponse } from "./types";

export const COLUMN_COUNT = 8;

export interface SectionData {
  readonly nodes: readonly ViewportNode[];
  readonly edges: readonly ViewportEdge[];
}

export interface GridContextValue {
  readonly domainId: string;
  readonly activeKey: string | null;
  readonly selectedKey: string | null;
  readonly expanded: ReadonlySet<string>;
  readonly activate: (key: string, node: ViewportNode) => void;
  readonly setActive: (key: string) => void;
  readonly collapse: (key: string) => void;
  readonly expand: (key: string, node: ViewportNode) => void;
  readonly report: (section: string, data: SectionData | null) => void;
  readonly focusRow: (key: string) => boolean;
}

export const GridContext = createContext<GridContextValue | undefined>(undefined);

function useGrid(): GridContextValue {
  const ctx = useContext(GridContext);
  if (ctx === undefined) throw new Error("GridContext missing");
  return ctx;
}

const useStyles = makeStyles({
  row: {
    cursor: "pointer",
    outlineOffset: "-2px",
    ":focus-visible": {
      outline: `2px solid ${tokens.colorStrokeFocus2}`,
    },
  },
  selected: { backgroundColor: tokens.colorNeutralBackground1Selected },
  cell: {
    padding: `${tokens.spacingVerticalXS} ${tokens.spacingHorizontalS}`,
    borderBottom: `1px solid ${tokens.colorNeutralStroke2}`,
    textAlign: "left",
  },
  inline: { display: "inline-flex", alignItems: "center", columnGap: tokens.spacingHorizontalXS },
  note: { color: tokens.colorNeutralForeground2, fontSize: tokens.fontSizeBase200 },
});

function rowKeyOf(section: string, node: ViewportNode): string {
  return `${section}|${node.id}`;
}

function isCluster(node: ViewportNode): boolean {
  return node.kind === "cluster";
}

interface NodeRowProps {
  readonly node: ViewportNode;
  readonly rowKey: string;
  readonly depth: number;
  readonly isFirst: boolean;
}

function NodeRow({ node, rowKey, depth, isFirst }: NodeRowProps): ReactElement {
  const styles = useStyles();
  const grid = useGrid();
  const cluster = isCluster(node);
  const isExpanded = grid.expanded.has(rowKey);
  const m = node.metrics;
  const tabbable = grid.activeKey === null ? isFirst : grid.activeKey === rowKey;
  const onKeyDown = (e: KeyboardEvent<HTMLTableRowElement>): void => {
    if (e.target !== e.currentTarget) return;
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      grid.activate(rowKey, node);
    } else if (e.key === "ArrowRight" && cluster && !isExpanded) {
      e.preventDefault();
      grid.expand(rowKey, node);
    } else if (e.key === "ArrowLeft" && cluster && isExpanded) {
      e.preventDefault();
      grid.collapse(rowKey);
    }
  };
  return (
    <tr
      className={mergeClasses(styles.row, grid.selectedKey === rowKey && styles.selected)}
      data-row-key={rowKey}
      data-testid="node-row"
      tabIndex={tabbable ? 0 : -1}
      aria-level={depth + 1}
      aria-selected={grid.selectedKey === rowKey}
      aria-expanded={cluster ? isExpanded : undefined}
      onFocus={(e) => {
        if (e.target === e.currentTarget) grid.setActive(rowKey);
      }}
      onClick={() => grid.activate(rowKey, node)}
      onKeyDown={onKeyDown}
    >
      <td className={styles.cell}>
        <span className={styles.inline} style={{ paddingLeft: `${depth * 20}px` }}>
          <KindIcon kind={node.kind} />
          <span data-testid="kind-text">{KIND_LABEL[node.kind]}</span>
        </span>
      </td>
      <td className={styles.cell}>
        <span data-testid="label">{node.label}</span>
        {cluster ? (
          <span className={styles.note}> ({isExpanded ? STRINGS.collapse : STRINGS.expand})</span>
        ) : null}
      </td>
      <td className={styles.cell}>{membersText(node)}</td>
      <td className={styles.cell}>{metricText(m.tokens)}</td>
      <td className={styles.cell}>{metricText(m.context_size)}</td>
      <td className={styles.cell}>{metricText(m.frequency)}</td>
      <td className={styles.cell}>{metricText(m.latency_p95_ms, " ms")}</td>
      <td className={styles.cell}>
        <span data-testid="health" data-health={m.health}>
          <HealthIndicator state={m.health} label={HEALTH_LABEL[m.health]} />
        </span>
      </td>
    </tr>
  );
}

function ClusterSection({
  node,
  rowKey,
  depth,
}: {
  readonly node: ViewportNode;
  readonly rowKey: string;
  readonly depth: number;
}): ReactElement {
  const grid = useGrid();
  const query = useViewport(grid.domainId, node.id);
  if (query.isError) {
    return (
      <tr>
        <td colSpan={COLUMN_COUNT} role="alert" data-testid="section-error">
          Could not load the members of {node.label}. This is not an empty result.
        </td>
      </tr>
    );
  }
  if (query.isPending) {
    return (
      <tr>
        <td colSpan={COLUMN_COUNT} aria-busy="true">
          <LoadingState label={STRINGS.loading} rows={1} />
        </td>
      </tr>
    );
  }
  return (
    <SectionRows query={query} section={rowKey} depth={depth} parentLabel={node.label} showStatus />
  );
}

export interface SectionRowsProps {
  readonly query: UseInfiniteQueryResult<
    InfiniteData<ViewportResponse, string | undefined>,
    ApiError
  >;
  readonly section: string;
  readonly depth: number;
  readonly parentLabel: string;
  readonly showStatus: boolean;
}

/** Rows for one loaded viewport section (the top level or one expanded cluster). */
export function SectionRows({
  query,
  section,
  depth,
  parentLabel,
  showStatus,
}: SectionRowsProps): ReactElement | null {
  const styles = useStyles();
  const grid = useGrid();
  const { report, focusRow } = grid;
  const pages = query.data?.pages;
  const nodes = pages?.flatMap((p) => p.nodes) ?? [];
  const last = pages?.[pages.length - 1];

  useEffect(() => {
    if (pages === undefined) return undefined;
    report(section, {
      nodes: pages.flatMap((p) => p.nodes),
      edges: pages.flatMap((p) => p.edges),
    });
    return () => report(section, null);
  }, [pages, report, section]);

  // Focus the first newly loaded row once it is committed to the DOM. The "Load more" button may
  // unmount (last page), so focus must never be left on it: fall back to the cluster row.
  const [pendingFocus, setPendingFocus] = useState<string | null>(null);
  const loadedCount = nodes.length;
  useLayoutEffect(() => {
    if (pendingFocus === null) return;
    if (focusRow(pendingFocus)) {
      setPendingFocus(null);
      return;
    }
    // The query observer may not have re-rendered with the new page yet: keep waiting (this effect
    // re-runs when the loaded row count changes). Once the row is loaded but still missing from
    // the DOM, fall back to the cluster row rather than leave focus on a removed element.
    const loaded = nodes.some((n) => rowKeyOf(section, n) === pendingFocus);
    if (loaded) {
      if (!focusRow(section)) focusRow(grid.activeKey ?? "");
      setPendingFocus(null);
    }
  }, [pendingFocus, loadedCount, focusRow, section, grid.activeKey]);

  if (last === undefined) return null;

  const loadMore = async (): Promise<void> => {
    const before = nodes.length;
    const res = await query.fetchNextPage();
    const all = res.data?.pages.flatMap((p) => p.nodes) ?? [];
    const firstNew = all[before];
    if (firstNew !== undefined) {
      setPendingFocus(rowKeyOf(section, firstNew));
    }
  };

  return (
    <>
      {nodes.map((node, i) => {
        const key = rowKeyOf(section, node);
        return (
          <FragmentRow
            key={key}
            node={node}
            rowKey={key}
            depth={depth}
            isFirst={section === "root" && i === 0}
          />
        );
      })}
      {showStatus ? (
        <tr>
          <td colSpan={COLUMN_COUNT} className={styles.note} data-testid="section-status">
            <span style={{ paddingLeft: `${depth * 20}px` }}>
              {parentLabel}:{" "}
              <span data-testid="section-coverage">{coverageText(last.coverage)}</span>
              {last.truncated ? (
                <>
                  {" "}
                  <span data-testid="section-truncated">
                    {truncationText(last.truncation_reason)}
                  </span>
                </>
              ) : null}
            </span>
          </td>
        </tr>
      ) : null}
      {query.hasNextPage ? (
        <tr>
          <td colSpan={COLUMN_COUNT} className={styles.cell}>
            <button
              type="button"
              disabled={query.isFetchingNextPage}
              aria-label={`${STRINGS.loadMore} in ${parentLabel}`}
              onClick={() => void loadMore()}
            >
              {STRINGS.loadMore}
            </button>
          </td>
        </tr>
      ) : null}
    </>
  );
}

function FragmentRow({ node, rowKey, depth, isFirst }: NodeRowProps): ReactElement {
  const grid = useGrid();
  return (
    <>
      <NodeRow node={node} rowKey={rowKey} depth={depth} isFirst={isFirst} />
      {isCluster(node) && grid.expanded.has(rowKey) ? (
        <ClusterSection node={node} rowKey={rowKey} depth={depth + 1} />
      ) : null}
    </>
  );
}
