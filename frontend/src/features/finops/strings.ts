export const STRINGS = {
  pageTitle: "Cost forecast",
  pageDescription:
    "Estimated and invoiced cost are shown separately and are never added together. The forecast is a trend projection with an uncertainty band.",
  toolbarLabel: "Forecast controls",
  history: "History (days)",
  horizon: "Horizon (days)",
  currency: "Currency",
  domainRequiredTitle: "Select a domain",
  domainRequired: "Pick a domain to see its cost forecast.",
  loading: "Loading forecast",
  failedTitle: "Could not load the forecast",
  failedBody: "The service did not return the forecast. Try again.",
  workspace: "Cost forecast",
  unknown: "unknown",
  incomplete: "incomplete",
  complete: "complete",
  estimated: "Estimated",
  invoiced: "Invoiced",
  neverSummed:
    "Estimated and invoiced cost are different bases. They are charted and totalled separately and never added together.",
  unavailablePrefix: "forecast unavailable",
  historyTotal: "History total",
  horizonActual: "Horizon actual",
  horizonForecast: "Horizon forecast",
  bandNote:
    "The band is the pair of dashed lower and upper bound lines, also listed as lower and upper columns in the table view.",
  noClaim: "This forecast is a projection only and makes no claim about cost reduction.",
  methodTitle: "Method",
  method: "Method",
  confidence: "Confidence",
  fitPoints: "Fit points",
  excludedDays: "Excluded incomplete days",
  asOf: "First forecast day",
  priceVersions: "Price versions",
  primaryPriceVersion: "Price version",
  tableTitle: "Table view",
  columns: {
    day: "Day",
    phase: "Phase",
    actual: "Actual",
    forecast: "Forecast",
    lower: "Lower bound",
    upper: "Upper bound",
    inBand: "Within band",
  },
  yes: "yes",
  no: "no",
  none: "none",
} as const;

export const HISTORY_OPTIONS = [7, 14, 30, 60, 90] as const;
export const HORIZON_OPTIONS = [1, 7, 14, 21, 31] as const;
export const CURRENCY_OPTIONS = ["USD", "EUR", "GBP", "CAD"] as const;
export const DEFAULT_HISTORY = 30;
export const DEFAULT_HORIZON = 14;
export const DEFAULT_CURRENCY = "USD";
