import { Dropdown, Label, Option, makeStyles, tokens } from "@fluentui/react-components";
import { useId, type ReactElement } from "react";
import { ForbiddenError } from "../../api/index.js";
import {
  DataTable,
  ErrorState,
  StatusPill,
  Timestamp,
  type DataTableColumn,
  type StatusTone,
} from "../../design-system";
import { ForbiddenState } from "../workspaces/ForbiddenState";
import type { AuditDomain } from "../audit/types";
import { countText, type Observation, type SummaryWord, type SupportStatus } from "./data";
import { STRINGS } from "./strings";

const useStyles = makeStyles({
  row: {
    display: "flex",
    alignItems: "center",
    columnGap: tokens.spacingHorizontalS,
    flexWrap: "wrap",
  },
  dropdown: { minWidth: "280px" },
});

/** Tones carry no verdict: present is informational, partial is a caution, the rest neutral. */
const SUMMARY_TONE: Record<SummaryWord, StatusTone> = {
  evidence_present: "info",
  evidence_partial: "warning",
  no_evidence: "neutral",
  customer_responsibility: "neutral",
};

export function SupportPill({ status }: { readonly status: SupportStatus }): ReactElement {
  return <StatusPill tone="neutral" label={STRINGS.support[status]} />;
}

export function SummaryPill({ word }: { readonly word: SummaryWord }): ReactElement {
  return <StatusPill tone={SUMMARY_TONE[word]} label={STRINGS.summary[word]} />;
}

/** One state for a failed call: 403 or a plain failure with a reference id when there is one. */
export function ProblemState({
  error,
  title,
  onRetry,
}: {
  readonly error: Error;
  readonly title: string;
  readonly onRetry: () => void;
}): ReactElement {
  if (error instanceof ForbiddenError) {
    return <ForbiddenState workspace={STRINGS.workspace} correlationId={error.correlationId} />;
  }
  const reference =
    "correlationId" in error && typeof error.correlationId === "string" && error.correlationId
      ? ` (reference ${error.correlationId})`
      : "";
  return (
    <div data-testid="error-state">
      <ErrorState title={title} message={`${STRINGS.failedBody}${reference}`} onRetry={onRetry} />
    </div>
  );
}

export function DomainPicker({
  domains,
  selected,
  onSelect,
}: {
  readonly domains: readonly AuditDomain[];
  readonly selected: AuditDomain | undefined;
  readonly onSelect: (domainId: string) => void;
}): ReactElement {
  const styles = useStyles();
  const id = useId();
  return (
    <div className={styles.row}>
      <Label htmlFor={id}>{STRINGS.domainLabel}</Label>
      <Dropdown
        id={id}
        className={styles.dropdown}
        placeholder={STRINGS.domainPlaceholder}
        value={selected === undefined ? "" : selected.display_name}
        selectedOptions={selected === undefined ? [] : [selected.domain_id]}
        onOptionSelect={(_e, option) => {
          if (option.optionValue !== undefined) onSelect(option.optionValue);
        }}
      >
        {domains.map((d) => (
          <Option key={d.domain_id} value={d.domain_id} text={d.display_name}>
            {d.display_name}
          </Option>
        ))}
      </Dropdown>
    </div>
  );
}

function records(obs: Observation): number | null {
  return obs.measures.find((m) => m.name === "records")?.value ?? null;
}

const OBSERVATION_COLUMNS: readonly DataTableColumn<Observation>[] = [
  { key: "source", header: STRINGS.observationColumns.source, render: (o) => o.source_id },
  {
    key: "status",
    header: STRINGS.observationColumns.status,
    render: (o) => (
      <StatusPill
        tone={o.status === "observed" ? "info" : o.status === "partial" ? "warning" : "neutral"}
        label={STRINGS.status[o.status]}
      />
    ),
  },
  {
    key: "reason",
    header: STRINGS.observationColumns.reason,
    render: (o) => o.reason_code ?? STRINGS.none,
  },
  {
    key: "records",
    header: STRINGS.observationColumns.records,
    render: (o) => countText(records(o), STRINGS.unknown),
  },
  {
    key: "newest",
    header: STRINGS.observationColumns.newest,
    render: (o) =>
      o.latest_at === null ? STRINGS.unknown : <Timestamp value={o.latest_at} grain="day" />,
  },
  {
    key: "capped",
    header: STRINGS.observationColumns.capped,
    render: (o) => (o.truncated ? STRINGS.yes : STRINGS.no),
  },
];

export function ObservationsTable({
  observations,
}: {
  readonly observations: readonly Observation[];
}): ReactElement {
  return (
    <DataTable
      label={STRINGS.observationsLabel}
      columns={OBSERVATION_COLUMNS}
      rows={observations}
      getRowId={(o) => o.source_id}
      getRowProps={(o) => ({ "data-testid": `observation-${o.source_id}` })}
    />
  );
}
