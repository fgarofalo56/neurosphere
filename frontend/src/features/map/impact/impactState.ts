/**
 * Pure incident-view state (no React, no sigma): what an impact response means for the nodes and
 * edges the map currently holds. The map and the table both read it.
 */
import type { Health, ImpactResponse, NodeKind, TruncationReason } from "../types";

/** The slice of the graph the impact state needs: which ids are currently on screen. */
export interface GraphPresence {
  hasNode(id: string): boolean;
  hasEdge(id: string): boolean;
}

export interface ImpactRow {
  readonly id: string;
  readonly kind: NodeKind;
  readonly label: string;
  readonly health: Health;
  /** True when the health is the dependents fallback rule, not a measured point. */
  readonly healthInferred: boolean;
  readonly depth: number;
  /** The node is part of the graph the map holds right now. */
  readonly onScreen: boolean;
}

export interface ImpactLevelRows {
  readonly depth: number;
  readonly rows: readonly ImpactRow[];
}

export interface ImpactState {
  readonly rootId: string;
  /** Every dependent, by depth (ascending). */
  readonly levels: readonly ImpactLevelRows[];
  /** Every dependent node id, whether on screen or not. */
  readonly nodeIds: ReadonlySet<string>;
  /** Every edge id the server named, whether on screen or not. */
  readonly edgeIds: ReadonlySet<string>;
  /** Dependents the map does not currently hold. */
  readonly offscreen: readonly ImpactRow[];
  /** Number of dependents (the root is not one). */
  readonly total: number;
  readonly truncated: boolean;
  readonly truncationReason: TruncationReason | null;
}

/** What the renderer highlights: the root plus the dependents and edges that are on screen. */
export interface ImpactSelection {
  readonly nodeIds: readonly string[];
  readonly edgeIds: readonly string[];
}

export function deriveImpact(response: ImpactResponse, graph: GraphPresence): ImpactState {
  const levels: ImpactLevelRows[] = [];
  const nodeIds = new Set<string>();
  const edgeIds = new Set<string>();
  const offscreen: ImpactRow[] = [];
  const sorted = [...response.levels].sort((a, b) => a.depth - b.depth);
  for (const level of sorted) {
    const rows: ImpactRow[] = [];
    for (const node of level.nodes) {
      if (nodeIds.has(node.id)) continue; // a node is listed once, at its shortest depth
      nodeIds.add(node.id);
      const row: ImpactRow = {
        id: node.id,
        kind: node.kind,
        label: node.label,
        health: node.health,
        healthInferred: node.health_inferred === true,
        depth: level.depth,
        onScreen: graph.hasNode(node.id),
      };
      rows.push(row);
      if (!row.onScreen) offscreen.push(row);
    }
    for (const id of level.edge_ids) edgeIds.add(id);
    levels.push({ depth: level.depth, rows });
  }
  return {
    rootId: response.node_id,
    levels,
    nodeIds,
    edgeIds,
    offscreen,
    total: nodeIds.size,
    truncated: response.truncated,
    truncationReason: response.truncation_reason,
  };
}

/**
 * What to highlight on the canvas, or null when the incident view is off (clear restores the
 * normal view). Ids the graph does not hold are left out.
 */
export function highlightOf(
  state: ImpactState | null,
  graph: GraphPresence,
): ImpactSelection | null {
  if (state === null) return null;
  const nodeIds = [state.rootId, ...state.nodeIds].filter((id) => graph.hasNode(id));
  const edgeIds = [...state.edgeIds].filter((id) => graph.hasEdge(id));
  return { nodeIds, edgeIds };
}

/** Does a node turning `failing` change this incident (the root or one of its dependents)? */
export function concernsImpact(state: ImpactState | null, nodeId: string): boolean {
  return state !== null && (state.rootId === nodeId || state.nodeIds.has(nodeId));
}
