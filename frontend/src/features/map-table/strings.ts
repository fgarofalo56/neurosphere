/** Every label lives here so tests assert exact text. Status is never colour alone. */
import type {
  Coverage,
  Health,
  NodeKind,
  Provenance,
  TruncationReason,
  ViewportNode,
} from "./types";

export const STRINGS = {
  title: "Map table",
  intro:
    "Table view of the same map data, for keyboard and screen reader use. Read-only; nothing here changes anything.",
  viewAsMap: "View as map",
  domainRequired: "Choose a domain to view its map.",
  loading: "Loading...",
  caption: "Map nodes",
  connectionsCaption: "Connections between loaded nodes",
  noConnections: "No connections among the loaded nodes.",
  empty: "No nodes found for this domain.",
  unknown: "Unknown",
  loadMore: "Load more",
  expand: "Expand",
  collapse: "Collapse",
  detailHeading: "Selected node",
  nothingSelected: "No node selected. Press Enter on a row to see its details.",
  keyboardHelp:
    "Keyboard: Tab to the table, Up and Down arrows move between rows, Enter or Space opens a row and expands clusters.",
  columns: {
    kind: "Kind",
    label: "Label",
    members: "Members",
    tokens: "Tokens",
    context: "Context size",
    frequency: "Frequency",
    latency: "Latency p95",
    health: "Health",
  },
  connections: {
    source: "Source",
    target: "Target",
    provenance: "Provenance",
  },
} as const;

export const KIND_LABEL: Readonly<Record<NodeKind, string>> = {
  person: "Person",
  agent: "Agent",
  sub_agent: "Sub-agent",
  model: "Model",
  source: "Source",
  cluster: "Cluster",
};

export const HEALTH_LABEL: Readonly<Record<Health, string>> = {
  ok: "Healthy",
  degraded: "Degraded",
  failing: "Failing",
  unknown: "Unknown",
};

export const PROVENANCE_LABEL: Readonly<Record<Provenance, string>> = {
  observed: "Observed",
  declared: "Declared",
  inferred: "Inferred",
};

const TRUNCATION_LABEL: Readonly<Record<TruncationReason, string>> = {
  node_budget: "node budget reached",
  edge_budget: "edge budget reached",
  scan_limit: "scan limit reached",
  traversal_incomplete: "traversal incomplete",
  timeout_ms: "time limit reached",
};

export function truncationText(reason: TruncationReason | null): string {
  const why = reason === null ? "reason not reported" : TRUNCATION_LABEL[reason];
  return `Truncated: ${why}. Not all nodes are shown.`;
}

export function coverageText(c: Coverage): string {
  switch (c.state) {
    case "complete":
      return "Coverage: complete";
    case "partial":
      return "Coverage: partial";
    case "delayed":
      return `Coverage: delayed${c.lag_seconds === null ? "" : ` (${c.lag_seconds} s lag)`}`;
    default:
      return "Coverage: unknown";
  }
}

/** Null is "Unknown", never 0 or blank. */
export function metricText(value: number | null, unit = ""): string {
  return value === null ? STRINGS.unknown : `${value}${unit}`;
}

export function membersText(node: ViewportNode): string {
  return node.kind === "cluster" ? metricText(node.member_count) : "-";
}
