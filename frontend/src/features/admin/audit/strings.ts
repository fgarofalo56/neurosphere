import { EXPORT_ROW_CAP, MAX_RANGE_DAYS } from "./hooks";

export const AUDIT_STRINGS = {
  title: "Audit search",
  description:
    "Search audit records across the domains you may read, review denials and check the SIEM sink. Actors are pseudonyms: they are never joined to a name.",
  filtersLabel: "Search filters",
  tabs: { search: "Search", denials: "Denials" },
  fields: {
    since: "From (required)",
    until: "To (required)",
    domain: "Domain id",
    operation: "Operation",
    kind: "Kind",
    outcome: "Outcome",
    actor: "Actor pseudonym",
    correlationId: "Correlation id",
  },
  any: "Any",
  apply: "Search",
  rangeHint: `Search and export cover at most ${MAX_RANGE_DAYS} days at a time.`,
  headers: {
    time: "Recorded",
    domain: "Domain",
    operation: "Operation",
    kind: "Kind",
    result: "Result",
    actor: "Actor",
    correlation: "Correlation id",
  },
  empty: "No audit records match these filters.",
  emptyDenials: "No denied attempts were recorded.",
  loading: "Loading audit records",
  noOutcome: "Not applicable",
  siem: {
    title: "SIEM sink",
    loading: "Loading SIEM status",
    sink: "Sink",
    state: "State",
    lastSuccess: "Last success",
    failures: "Consecutive failures",
    lastReason: "Last failure reason",
    never: "Never",
    none: "None",
    state_: { ok: "OK", disabled: "Disabled", failed: "Failed", not_built: "Not built" },
  },
  export: {
    title: "Export",
    ndjson: "Export NDJSON",
    csv: "Export CSV",
    cap: `An export holds at most ${EXPORT_ROW_CAP.toLocaleString("en-US")} rows and uses the filters and time range above.`,
    notice: "Every export is recorded on the audit chain of each domain it covers.",
    forbidden:
      "Export is disabled: the service declined it (it needs the audit export permission). You can still search.",
    done: (rows: number | undefined, name: string): string =>
      rows === undefined ? `Downloaded ${name}.` : `Downloaded ${name} with ${rows} rows.`,
    truncated: (cap: number): string =>
      `The export was cut at the row cap of ${cap.toLocaleString("en-US")}. Narrow the filters or the time range for the rest.`,
  },
} as const;
