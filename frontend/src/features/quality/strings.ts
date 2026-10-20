/** Every user-visible string for quality lives here so tests assert exact values. */
export const STRINGS = {
  unknown: "unknown",
  title: "Agent quality",
  loading: "Loading...",
  domainRequired: "Choose a domain to view quality.",
  domainLabel: "Domain",
  subjectLabel: "Subject (optional)",
  apply: "Apply filters",
  forbidden: "You do not have access to this domain",
  unavailable: "Quality results are unavailable",
  unavailableDetail:
    "The service could not be reached. This is not an empty result. Try again later.",
  uncalibrated: "Uncalibrated",
  calibrated: "Calibrated",
  notApplicable: "Calibration not applicable",
  uncalibratedNote: "Uncalibrated judge score: not validated against human labels",
  notEstimable: "not estimable",
  pilot: {
    title: "Pilot-set grounded-answer rate",
    notEstimableReason: "Not enough pilot data to estimate a rate.",
    estimate: "Estimate",
    sampleSize: "Sample size (n)",
    interval: "Interval",
    method: "Method",
  },
  sections: {
    trends: "Quality trends",
    coverage: "Sampling coverage by stratum",
    labels: "Human label coverage",
    drift: "Drift alerts",
  },
  trendHeaders: {
    bucket: "Period",
    value: "Score",
    interval: "Uncertainty",
    n: "Sample size",
    judge: "Judge",
    calibration: "Calibration",
  },
  coverageHeaders: {
    stratum: "Stratum",
    sampled: "Sampled",
    population: "Population",
    fraction: "Coverage",
  },
  labelHeaders: { judged: "Judged items", labelled: "With human label", missing: "Missing label" },
  driftHeaders: {
    dimension: "Dimension",
    subject: "Subject",
    detected: "Detected",
    statistic: "Statistic",
    threshold: "Threshold",
  },
  noTrends: "No quality trend data.",
  noCoverage: "No coverage data.",
  noDrift: "No drift alerts.",
} as const;

/** Null and undefined render the literal "unknown", never 0. */
export function orUnknown(value: string | number | null | undefined): string {
  if (value === null || value === undefined) return STRINGS.unknown;
  const text = String(value);
  return text.trim() === "" ? STRINGS.unknown : text;
}

export function numberText(value: number | null | undefined): string {
  if (value === null || value === undefined) return STRINGS.unknown;
  return String(Number(value.toFixed(4)));
}

export function fractionText(value: number | null | undefined): string {
  if (value === null || value === undefined) return STRINGS.unknown;
  return `${Number((value * 100).toFixed(2))}%`;
}

export function levelText(level: number | null | undefined): string {
  return level === null || level === undefined
    ? STRINGS.unknown
    : `${Number((level * 100).toFixed(2))}% level`;
}
