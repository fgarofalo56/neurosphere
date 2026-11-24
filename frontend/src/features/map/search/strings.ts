/** Every label of the map search lives here so tests assert exact text. */
export const SEARCH_STRINGS = {
  label: "Search the map",
  placeholder: "Search nodes (2+ characters)",
  hint: "Type at least 2 characters. Arrow keys move, Enter jumps to the node, Escape closes.",
  searching: "Searching",
  noMatches: "No matching nodes",
  failed: "Search failed. Try again.",
  count: (n: number) => `${n} ${n === 1 ? "match" : "matches"}`,
  truncated: (reason: string) => `Results are incomplete: ${reason}. Narrow the search.`,
  truncatedFallback: "more matches exist than were scanned",
  unknownValue: "unknown",
  row: (label: string, kind: string, environment: string, health: string) =>
    `${label}, ${kind}, environment ${environment}, health ${health}`,
  jumpFailed: "That node could not be loaded onto the map.",
  jumpTruncated: (reason: string) => `The neighbourhood of this node is incomplete: ${reason}.`,
  jumpDropped: (n: number) =>
    `${n} distant ${n === 1 ? "node was" : "nodes were"} removed from the view to stay within the node limit.`,
  jumpSkipped: (n: number) =>
    `${n} ${n === 1 ? "neighbour does" : "neighbours do"} not fit within the node limit.`,
  jumped: (label: string) => `Jumped to ${label}`,
} as const;
