/** Every label for the map lives here so tests assert exact text. */
import type {
  CoverageState,
  Health,
  NodeKind,
  Provenance,
  SizeMetric,
  TruncationReason,
} from "./types";

export const STRINGS = {
  title: "Live map",
  intro:
    "Agent topology for one domain. Pseudonyms are shown exactly as served. This view is read-only.",
  domainRequired: "Choose a domain to view its map.",
  domainLabel: "Domain",
  domainSubmit: "Show map",
  loading: "Loading map...",
  mapRegionName: "Agent topology map (WebGL graphic). The table view is the accessible equivalent.",
  viewAsTable: "View as table",
  webglUnavailable:
    "This browser could not start the WebGL map. Use the table view, which shows the same data.",
  errorTitle: "Could not load the map",
  errorBody: "The request failed. This is not an empty map.",
  empty: "No nodes in this domain yet.",
  nodeCount: (nodes: number, edges: number) => `${nodes} nodes, ${edges} edges shown`,
  unknown: "unknown",
  // Motion
  reduceMotion: "Reduce motion",
  reduceMotionSystem: "Reduce motion (set by your system preference)",
  edgeAnimationOn: "Observed edges animate",
  edgeAnimationOff: "Edge animation is off",
  // Truncation
  truncatedTitle: "Partial view",
  truncatedBody: (reason: string) =>
    `Not every node is shown (${reason}). Expand a cluster or load more to see further.`,
  loadMore: "Load more",
  loadingMore: "Loading more...",
  budgetReached: "The 2000-node display budget is reached. No more nodes can be loaded.",
  loadMoreFailed: "Could not load more. Try again.",
  // Legends
  legendHeading: "Legend",
  sizeBy: "Size by",
  colourBy: "Colour by health",
  nodeKinds: "Node types",
  edgeStyles: "Edge styles",
  clusterSizeNote: "Clusters are sized by member count.",
  unknownLegend: "no data (never shown as 0)",
  // Panel
  panelHeading: "Selected node",
  panelClose: "Close",
  expandCluster: "Expand cluster",
  members: (n: number) => `${n} members`,
  linksHeading: "Related views",
  linkCost: "Cost dashboard",
  linkLatency: "Latency dashboard",
  linkRecommendations: "Recommendations",
  linkReplay: "Trace replay",
  // Live
  liveConnecting: "Live updates: connecting",
  liveLive: "Live updates: connected",
  liveReconnecting: "Live updates: connection lost, reconnecting",
  liveDisconnected: "Live updates: disconnected. The map is a snapshot and is not updating.",
  liveUnavailable: "Live updates unavailable. The map is a snapshot and is not updating.",
  liveUnauthenticated: "Live updates: sign-in expired. The map is a snapshot and is not updating.",
  liveRevoked:
    "Live updates stopped: your access to this domain was revoked or is not permitted. The map is a stale snapshot.",
} as const;

export const KIND_LABEL: Readonly<Record<NodeKind, string>> = {
  person: "Person",
  agent: "Agent",
  sub_agent: "Sub-agent",
  model: "Model",
  source: "Source",
  cluster: "Cluster",
};

export const SIZE_METRIC_LABEL: Readonly<Record<SizeMetric, string>> = {
  tokens: "Tokens",
  context_size: "Context size",
  frequency: "Frequency",
  latency_p95_ms: "Latency (p95 ms)",
};

export const HEALTH_LABEL: Readonly<Record<Health, string>> = {
  ok: "ok",
  degraded: "degraded",
  failing: "failing",
  unknown: "unknown",
};

export const PROVENANCE_LABEL: Readonly<Record<Provenance, string>> = {
  observed: "Observed (solid; animated when motion is allowed)",
  declared: "Declared (dashed, static)",
  inferred: "Inferred (dotted, static)",
};

export const TRUNCATION_REASON_LABEL: Readonly<Record<TruncationReason, string>> = {
  node_budget: "node budget reached",
  edge_budget: "edge budget reached",
  scan_limit: "scan limit reached",
  traversal_incomplete: "traversal incomplete",
  timeout_ms: "query timed out",
};

export function coverageText(
  state: CoverageState,
  lagSeconds: number | null,
  asOf: string | null,
): string {
  const asOfText = asOf !== null ? ` (as of ${asOf})` : "";
  switch (state) {
    case "complete":
      return `Coverage complete${asOfText}`;
    case "partial":
      return `Partial coverage: some data is missing${asOfText}`;
    case "delayed":
      return lagSeconds !== null
        ? `Delayed: data is ${Math.round(lagSeconds)} s behind${asOfText}`
        : `Delayed: lag is not known${asOfText}`;
    case "unknown":
      return `Coverage unknown${asOfText}`;
  }
}
