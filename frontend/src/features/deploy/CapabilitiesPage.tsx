import {
  Button,
  Field,
  Input,
  Link,
  Radio,
  RadioGroup,
  Text,
  makeStyles,
  tokens,
} from "@fluentui/react-components";
import { useState, type ReactElement } from "react";
import { ForbiddenError } from "../../api/index.js";
import {
  DataTable,
  EmptyState,
  ErrorState,
  LoadingState,
  PageTemplate,
  StatusPill,
  type DataTableColumn,
  type StatusTone,
} from "../../design-system";
import { ForbiddenState } from "../workspaces";
import { rowState, useCapabilities, type CapabilityFilter } from "./data";
import { CLOUD_OPTIONS, STRINGS, type Cloud } from "./strings";
import type { CapabilityRow } from "./types";

const useStyles = makeStyles({
  stack: { display: "flex", flexDirection: "column", rowGap: tokens.spacingVerticalM },
  row: { display: "flex", flexWrap: "wrap", gap: tokens.spacingHorizontalM, alignItems: "end" },
  muted: { color: tokens.colorNeutralForeground2, fontSize: tokens.fontSizeBase200 },
  disabledText: { color: tokens.colorNeutralForeground3 },
  // Fluent's Link only underlines on focus; WCAG 2.4.7 needs a visible ring in every theme.
  link: {
    ":focus-visible": { outline: `2px solid ${tokens.colorStrokeFocus2}`, outlineOffset: "2px" },
  },
});

const REGION_RE = /^[a-z][a-z0-9]{2,39}$/;

const AVAILABILITY_TONE: Record<CapabilityRow["availability"], StatusTone> = {
  available: "success",
  preview: "warning",
  unavailable: "danger",
  unverified: "warning",
};

function columns(cloud: Cloud, linkClass: string): readonly DataTableColumn<CapabilityRow>[] {
  const c = STRINGS.capColumns;
  return [
    {
      key: "state",
      header: c.state,
      render: (r) => {
        const s = rowState(r, cloud);
        return s.enabled ? (
          <StatusPill label={STRINGS.capEnabled} tone="success" />
        ) : (
          <span>
            <StatusPill label={STRINGS.capDisabled} tone="neutral" />{" "}
            <Text data-testid="cap-reason">{s.reason}</Text>
          </span>
        );
      },
    },
    { key: "service", header: c.service, render: (r) => `${r.service} / ${r.feature}` },
    { key: "cloud", header: c.cloud, render: (r) => r.cloud },
    { key: "region", header: c.region, render: (r) => r.region },
    { key: "sku", header: c.sku, render: (r) => r.sku ?? "" },
    {
      key: "availability",
      header: c.availability,
      render: (r) => <StatusPill label={r.availability} tone={AVAILABILITY_TONE[r.availability]} />,
    },
    { key: "ga", header: c.ga, render: (r) => r.ga_status },
    { key: "scope", header: c.scope, render: (r) => r.authorization_scope },
    {
      key: "source",
      header: c.source,
      render: (r) =>
        r.source_url.startsWith("https://") ? (
          <Link className={linkClass} href={r.source_url} target="_blank" rel="noopener noreferrer">
            {STRINGS.sourceLink}
          </Link>
        ) : (
          r.source_url
        ),
    },
    { key: "observed", header: c.observed, render: (r) => r.observed_on },
  ];
}

export function CapabilitiesPage(): ReactElement {
  const styles = useStyles();
  const [cloud, setCloud] = useState<Cloud>("commercial");
  const [regionInput, setRegionInput] = useState("");
  const [applied, setApplied] = useState<CapabilityFilter>({ cloud: "commercial", region: "" });
  const regionError =
    regionInput !== "" && !REGION_RE.test(regionInput) ? STRINGS.capRegionInvalid : undefined;
  const query = useCapabilities(applied);

  function apply(): void {
    if (regionError !== undefined) return;
    setApplied({ cloud, region: regionInput });
  }

  const toolbar = (
    <div className={styles.row}>
      <Field label={STRINGS.capCloud}>
        <RadioGroup
          layout="horizontal"
          value={cloud}
          onChange={(_, d) => setCloud(d.value as Cloud)}
        >
          {CLOUD_OPTIONS.map((c) => (
            <Radio key={c} value={c} label={c} />
          ))}
        </RadioGroup>
      </Field>
      <Field
        label={STRINGS.capRegion}
        validationState={regionError === undefined ? "none" : "error"}
        validationMessage={regionError}
      >
        <Input value={regionInput} onChange={(_, d) => setRegionInput(d.value.trim())} />
      </Field>
      <Button onClick={apply} data-testid="cap-apply">
        {STRINGS.capApply}
      </Button>
    </div>
  );

  let body: ReactElement;
  if (query.isPending) {
    body = <LoadingState label={STRINGS.capLoading} />;
  } else if (query.isError) {
    body =
      query.error instanceof ForbiddenError ? (
        <ForbiddenState
          workspace={STRINGS.forbiddenWorkspace}
          correlationId={query.error.correlationId}
        />
      ) : (
        <ErrorState
          title={STRINGS.capFailed}
          testId="cap-error"
          onRetry={() => void query.refetch()}
        />
      );
  } else {
    // Defensive: a row of another cloud is never shown for the selected one, whatever the API sent.
    const rows = query.data.items.filter((r) => r.cloud === applied.cloud);
    body =
      rows.length === 0 ? (
        <EmptyState
          title={STRINGS.capEmptyTitle}
          description={STRINGS.capEmptyBody}
          testId="cap-empty"
        />
      ) : (
        <div className={styles.stack}>
          <Text className={styles.muted}>
            {STRINGS.capMeta(query.data.matrix_version, query.data.observed_at)}
          </Text>
          <DataTable
            label={STRINGS.capTable}
            columns={columns(applied.cloud, styles.link)}
            rows={rows}
            getRowId={(r) => r.id}
            getRowProps={(r) => ({
              "data-testid": "cap-row",
              "data-enabled": String(rowState(r, applied.cloud).enabled),
            })}
          />
        </div>
      );
  }

  return (
    <PageTemplate
      title={STRINGS.capabilitiesTitle}
      description={STRINGS.capabilitiesDescription}
      toolbar={toolbar}
      toolbarLabel="Capability filters"
    >
      {body}
    </PageTemplate>
  );
}
