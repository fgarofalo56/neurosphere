import { Button, makeStyles, tokens } from "@fluentui/react-components";
import type { ReactElement } from "react";
import {
  DataTable,
  HealthIndicator,
  KpiCard,
  PageTemplate,
  Sparkline,
  StatusPill,
  Timestamp,
  formatCurrency,
  formatNumber,
  type DataTableColumn,
  type StatusTone,
  type UiStyleId,
} from "../../../design-system";
import {
  ACTIVITY_ROWS,
  EUR_LAST_7,
  EUR_TOTAL_7,
  MOCKUP_NOW,
  USD_LAST_7,
  USD_TOTAL_7,
  type ActivityRow,
} from "./fixtures";
import { MockupFrame, Panel, type MockupMode } from "./MockupFrame";

const useStyles = makeStyles({
  stack: { display: "flex", flexDirection: "column", rowGap: tokens.spacingVerticalM },
  stackOps: { display: "flex", flexDirection: "column", rowGap: tokens.spacingVerticalS },
  rows: { display: "flex", flexDirection: "column", rowGap: tokens.spacingVerticalS },
  line: {
    display: "flex",
    alignItems: "center",
    justifyContent: "space-between",
    columnGap: tokens.spacingHorizontalM,
    fontSize: tokens.fontSizeBase300,
  },
  // Ops console: one dense KPI row, then a 2/3 - 1/3 split.
  opsSplit: {
    display: "grid",
    gridTemplateColumns: "minmax(0, 2fr) minmax(0, 1fr)",
    columnGap: tokens.spacingHorizontalS,
    alignItems: "start",
  },
  // Enterprise Fluent: 3x2 card grid, activity full width, then two comfortable panels.
  entRow: {
    display: "grid",
    gridTemplateColumns: "repeat(2, minmax(0, 1fr))",
    columnGap: tokens.spacingHorizontalM,
    alignItems: "start",
  },
  muted: { color: tokens.colorNeutralForeground2, fontSize: tokens.fontSizeBase200 },
});

const STATE_TONE: Record<ActivityRow["state"], StatusTone> = {
  "Pending review": "info",
  "Awaiting approval": "warning",
  Applied: "success",
  Failed: "danger",
};

const COLUMNS: readonly DataTableColumn<ActivityRow>[] = [
  { key: "item", header: "Item", width: "40%", minWidth: "240px", render: (r) => r.item },
  { key: "kind", header: "Type", width: "14%", render: (r) => r.kind },
  {
    key: "state",
    header: "State",
    width: "20%",
    render: (r) => <StatusPill label={r.state} tone={STATE_TONE[r.state]} />,
  },
  {
    key: "at",
    header: "Updated",
    minWidth: "140px",
    render: (r) => <Timestamp value={r.at} now={MOCKUP_NOW} />,
  },
];

export function HomeMockup({
  styleId,
  mode,
}: {
  readonly styleId: UiStyleId;
  readonly mode: MockupMode;
}): ReactElement {
  const styles = useStyles();
  const ops = styleId === "ops-console";
  const spark = ops ? { width: 120, height: 22 } : { width: 200, height: 32 };

  const activity = (
    <Panel title="Recent governance activity" note="5 of 25+">
      <DataTable
        label="Recent governance activity"
        columns={COLUMNS}
        rows={ACTIVITY_ROWS}
        getRowId={(r) => r.id}
      />
    </Panel>
  );
  const completeness = (
    <Panel title="Data completeness">
      <StatusPill
        tone="warning"
        label="Incomplete total: 3 of 14 billing days still await invoice data, so invoiced totals are partial and are never summed across currencies."
      />
      <div className={styles.rows}>
        <div className={styles.line}>
          <span>Cost export</span>
          <HealthIndicator state="degraded" label="Late by 2 days" />
        </div>
        <div className={styles.line}>
          <span>Telemetry ingest</span>
          <HealthIndicator state="ok" />
        </div>
        <div className={styles.line}>
          <span>Billing feed connector</span>
          <HealthIndicator state="failing" />
        </div>
        <div className={styles.line}>
          <span>Wiki connector</span>
          <HealthIndicator state="unknown" />
        </div>
      </div>
    </Panel>
  );
  const coverage = (
    <Panel title="Map coverage">
      <div className={styles.line}>
        <span>Agents with a known model</span>
        <HealthIndicator state="ok" label="38 of 41" />
      </div>
      <div className={styles.line}>
        <span>Models with a known data source</span>
        <HealthIndicator state="degraded" label="9 of 12" />
      </div>
      <span className={styles.muted}>
        Last full scan <Timestamp value="2026-10-24T08:30:00Z" now={MOCKUP_NOW} />
      </span>
    </Panel>
  );

  return (
    <MockupFrame styleId={styleId} mode={mode} active="Home">
      <PageTemplate
        title="Home"
        description="Cost, review work and map coverage for contoso-prod, last 7 days."
        actions={<Button appearance="primary">Create report</Button>}
        layout="stack"
        kpis={
          <>
            <KpiCard
              label="Cost, last 7 days (USD)"
              value={formatCurrency(USD_TOTAL_7, "USD", { maximumFractionDigits: 0 })}
              delta={{ text: "+4.2% vs previous 7 days", direction: "up" }}
              accent="ok"
              sparkline={
                <Sparkline
                  values={USD_LAST_7}
                  label="Daily estimated cost in USD"
                  kind="estimated"
                  unit="currency"
                  currency="USD"
                  {...spark}
                />
              }
            />
            <KpiCard
              label="Cost, last 7 days (EUR)"
              value={formatCurrency(EUR_TOTAL_7, "EUR", { maximumFractionDigits: 0 })}
              delta={{ text: "-1.8% vs previous 7 days", direction: "down" }}
              accent="ok"
              sparkline={
                <Sparkline
                  values={EUR_LAST_7}
                  label="Daily estimated cost in EUR"
                  kind="estimated"
                  unit="currency"
                  currency="EUR"
                  {...spark}
                />
              }
            />
            <KpiCard
              label="Review queue"
              value={`${formatNumber(25)}+`}
              delta={{ text: "more pages not loaded", direction: "flat" }}
              accent="unknown"
            />
            <KpiCard label="Awaiting actions" value={formatNumber(7)} status="degraded" />
            <KpiCard label="Map coverage" value="91%" status="ok" />
            <KpiCard label="Reports" value={formatNumber(12)} accent="ok" />
          </>
        }
      >
        {ops ? (
          <div className={styles.opsSplit}>
            {activity}
            <div className={styles.stackOps}>
              {completeness}
              {coverage}
            </div>
          </div>
        ) : (
          <>
            {activity}
            <div className={styles.entRow}>
              {completeness}
              {coverage}
            </div>
          </>
        )}
      </PageTemplate>
    </MockupFrame>
  );
}
