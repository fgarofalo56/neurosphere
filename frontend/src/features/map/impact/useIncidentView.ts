import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { createBurstDebouncer } from "../hooks";
import type { MapGraph } from "../mapGraph";
import type { Health, SearchMatch, ViewportNode } from "../types";
import { NULL_METRICS } from "../mapGraph";
import {
  concernsImpact,
  deriveImpact,
  highlightOf,
  type ImpactRow,
  type ImpactSelection,
  type ImpactState,
} from "./impactState";
import { DEFAULT_IMPACT_DEPTH, clampDepth, useMapImpact } from "./useMapImpact";

/** A live change settles for this long before the impact is recomputed. */
export const IMPACT_RECOMPUTE_MS = 2000;
/** The keyboard shortcut (documented in the panel): toggles the incident view of the selection. */
export const IMPACT_SHORTCUT_KEY = "i";

export interface IncidentBanner {
  readonly nodeId: string;
  readonly label: string;
}

export interface IncidentOptions {
  readonly domainId: string;
  readonly mapGraph: MapGraph;
  readonly selectedId: string | null;
  /** Nodes the user pinned: they start the incident view by themselves, like the selection. */
  readonly pinnedIds?: ReadonlySet<string>;
  /** Bumped whenever the graph changed: on-screen membership is recomputed. */
  readonly version: number;
}

export interface IncidentView {
  /** The node whose dependents are shown; null while the incident view is off. */
  readonly target: string | null;
  readonly targetLabel: string;
  readonly depth: number;
  readonly setDepth: (depth: number) => void;
  readonly start: (nodeId: string) => void;
  readonly clear: () => void;
  readonly state: ImpactState | null;
  readonly highlight: ImpactSelection | null;
  readonly loading: boolean;
  readonly failed: boolean;
  /** Offer for a node that turned failing and is not the selection; never moves the map. */
  readonly banner: IncidentBanner | null;
  readonly dismissBanner: () => void;
  /** Run a delta application and react to health changes it caused. */
  readonly handleDelta: (nodes: readonly ViewportNode[], apply: () => void) => void;
  /** A topology message arrived: the dependents may have changed. */
  readonly onTopology: () => void;
  /** A search-match shaped value for an off-screen row, for the shared jump. */
  readonly matchFor: (row: ImpactRow) => SearchMatch;
}

function healthOf(graph: MapGraph, id: string): Health | undefined {
  return graph.graph.hasNode(id) ? graph.graph.getNodeAttribute(id, "metrics").health : undefined;
}

function isEditable(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  const tag = target.tagName;
  return tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT" || target.isContentEditable;
}

/**
 * Incident view of the live map: the dependents of one node, highlighted and listed, kept current
 * while the data moves. It recomputes (debounced) when the node or one of its dependents turns
 * failing or the topology changes, starts by itself only for the selected or pinned node, and for
 * any other node that turns failing it offers a banner instead of moving anything.
 */
export function useIncidentView(options: IncidentOptions): IncidentView {
  const { domainId, mapGraph, selectedId, version } = options;
  const [target, setTarget] = useState<string | null>(null);
  const [depth, setDepthState] = useState(DEFAULT_IMPACT_DEPTH);
  const [banner, setBanner] = useState<IncidentBanner | null>(null);
  const query = useMapImpact(domainId, target, depth);

  const response = target !== null && query.data?.node_id === target ? query.data : undefined;
  const state = useMemo(() => {
    // `version` re-evaluates which dependents are on screen after a merge or refetch.
    void version;
    return response === undefined ? null : deriveImpact(response, mapGraph.graph);
  }, [response, mapGraph, version]);
  const highlight = useMemo(() => {
    void version;
    return target === null ? null : highlightOf(state ?? emptyFor(target), mapGraph.graph);
  }, [state, target, mapGraph, version]);

  // Latest values for the callbacks the live client holds on to.
  const latest = useRef({
    target,
    state,
    selectedId,
    pinned: options.pinnedIds,
    refetch: query.refetch,
  });
  latest.current = { target, state, selectedId, pinned: options.pinnedIds, refetch: query.refetch };

  const recompute = useMemo(
    () =>
      createBurstDebouncer(
        () => void latest.current.refetch(),
        IMPACT_RECOMPUTE_MS,
        IMPACT_RECOMPUTE_MS * 5,
      ),
    [],
  );
  useEffect(() => () => recompute.cancel(), [recompute]);

  const start = useCallback((nodeId: string) => {
    setBanner(null);
    setTarget(nodeId);
  }, []);
  const clear = useCallback(() => {
    recompute.cancel();
    setTarget(null);
    setBanner(null);
  }, [recompute]);
  const setDepth = useCallback((next: number) => setDepthState(clampDepth(next)), []);
  const dismissBanner = useCallback(() => setBanner(null), []);

  // Filters or a revoked session clear the graph: an incident view of a node that is gone ends.
  useEffect(() => {
    if (target !== null && !mapGraph.graph.hasNode(target) && version > 0) clear();
  }, [target, mapGraph, version, clear]);

  const handleDelta = useCallback(
    (nodes: readonly ViewportNode[], apply: () => void) => {
      const before = new Map<string, Health | undefined>();
      for (const n of nodes) before.set(n.id, healthOf(mapGraph, n.id));
      apply();
      let recomputeNeeded = false;
      for (const n of nodes) {
        if (n.kind === "cluster" || !mapGraph.graph.hasNode(n.id)) continue;
        const was = before.get(n.id);
        const now = healthOf(mapGraph, n.id);
        if (now !== "failing" || was === undefined || was === "failing") continue; // not newly failing
        const {
          target: current,
          state: currentState,
          selectedId: selected,
          pinned,
        } = latest.current;
        if (n.id === selected || pinned?.has(n.id) === true) {
          // The user is looking at it: start (or move) the incident view for it.
          if (current === n.id) recomputeNeeded = true;
          else {
            setBanner(null);
            setTarget(n.id);
          }
        } else if (current !== null && concernsImpact(currentState, n.id)) {
          recomputeNeeded = true;
        } else {
          const attrs = mapGraph.graph.getNodeAttributes(n.id);
          setBanner({ nodeId: n.id, label: attrs.label });
        }
      }
      if (recomputeNeeded) recompute.trigger();
    },
    [mapGraph, recompute],
  );

  const onTopology = useCallback(() => {
    if (latest.current.target !== null) recompute.trigger();
  }, [recompute]);

  // Keyboard shortcut: toggles the incident view of the selected node (not while typing).
  useEffect(() => {
    const onKey = (event: KeyboardEvent): void => {
      if (event.key.toLowerCase() !== IMPACT_SHORTCUT_KEY) return;
      if (event.ctrlKey || event.metaKey || event.altKey || isEditable(event.target)) return;
      const { selectedId: selected, target: current } = latest.current;
      if (selected === null || !mapGraph.graph.hasNode(selected)) return;
      if (mapGraph.graph.getNodeAttribute(selected, "kind") === "cluster") return;
      if (current === selected) clear();
      else start(selected);
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [mapGraph, start, clear]);

  const matchFor = useCallback(
    (row: ImpactRow): SearchMatch => ({
      node: {
        id: row.id,
        kind: row.kind,
        label: row.label,
        cluster_id: null,
        member_count: null,
        metrics: { ...NULL_METRICS, health: row.health },
      },
      cluster_id: "",
    }),
    [],
  );

  const targetLabel =
    target !== null && mapGraph.graph.hasNode(target)
      ? mapGraph.graph.getNodeAttribute(target, "label")
      : (target ?? "");

  return {
    target,
    targetLabel,
    depth,
    setDepth,
    start,
    clear,
    state,
    highlight,
    loading: target !== null && state === null && query.isFetching,
    failed: target !== null && query.isError,
    banner,
    dismissBanner,
    handleDelta,
    onTopology,
    matchFor,
  };
}

/** Before the first answer the root alone is highlighted (the rest is still unknown). */
function emptyFor(target: string): ImpactState {
  return {
    rootId: target,
    levels: [],
    nodeIds: new Set(),
    edgeIds: new Set(),
    offscreen: [],
    total: 0,
    truncated: false,
    truncationReason: null,
  };
}
