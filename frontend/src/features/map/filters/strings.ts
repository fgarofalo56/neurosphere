/** Every label of the filter bar lives here so tests assert exact text. */
export const FILTER_STRINGS = {
  barLabel: "Map filters",
  all: "All",
  nodeType: "Node type",
  environment: "Environment",
  cloud: "Cloud",
  health: "Health",
  tag: "Tag",
  tagHint: "Lowercase letters, digits, dot, underscore or hyphen; press Enter to apply.",
  tagInvalid:
    "Not a valid tag. Use 1 to 63 lowercase letters, digits, dots, underscores or hyphens, starting with a letter or digit.",
  applyTag: "Apply tag",
  optionsUnavailable: "Filter options could not be loaded; filters you set still apply.",
  optionWithCount: (label: string, count: number) => `${label} (${count})`,
  clearAll: (n: number) => `${n} ${n === 1 ? "filter" : "filters"} applied, clear all`,
} as const;
