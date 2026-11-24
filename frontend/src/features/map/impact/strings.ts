/** Every label of the incident view lives here so tests assert exact text. */
export const IMPACT_STRINGS = {
  showImpact: "Show impact",
  clearImpact: "Clear impact view",
  panelLabel: "Impact of the selected node",
  heading: "Depends on this node",
  intro: (label: string) => `Nodes that depend on ${label}, by distance.`,
  shortcut: "Keyboard shortcut: press I to show or clear the impact of the selected node.",
  depthLabel: "Impact depth (levels)",
  loading: "Loading impact",
  failed: "The impact could not be loaded. The map is unchanged.",
  none: (depth: number) =>
    `Nothing depends on this node within ${depth} ${depth === 1 ? "level" : "levels"}.`,
  levelHeading: (depth: number) => `Depth ${depth}`,
  row: (label: string, kind: string, health: string) => `${label}, ${kind}, health ${health}`,
  inferred: "inferred from its dependents",
  offscreenHeading: "Not on the map",
  offscreenNote: "These dependents are not in the current view.",
  showOnMap: "Show on map",
  showOnMapNamed: (label: string) => `Show ${label} on map`,
  truncated: (reason: string) => `The list is incomplete: ${reason}.`,
  truncatedFallback: "more dependents exist than were scanned",
  affected: (n: number, label: string) =>
    `${n} ${n === 1 ? "dependent" : "dependents"} affected by ${label}`,
  bannerText: (label: string) => `${label} just turned failing.`,
  bannerShow: "Show impact",
  bannerDismiss: "Dismiss",
} as const;
