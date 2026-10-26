import { Button, makeStyles, tokens } from "@fluentui/react-components";
import type { ReactElement } from "react";
import {
  DataTable,
  HealthIndicator,
  KpiCard,
  PageTemplate,
  StatusPill,
  TimeSeriesChart,
  Timestamp,
  formatCurrency,
  type DataTableColumn,
  type UiStyleId,
} from "../../../design-system";
import { COST_ROWS, EUR_SERIES, MOCKUP_NOW, USD_SERIES, type CostRow } from "./fixtures";
import { MockupFrame, Panel, type MockupMode } from "./MockupFrame";

const useStyles = makeStyles({
  charts: {
    display: "grid",
    gridTemplateColumns: "repeat(auto-fit, minmax(min(100%, 520px), 1fr))",
    columnGap: tokens.spacingHorizontalM,
    rowGap: tokens.spacingVerticalM,
  },
  num: { fontVariantNumeric: "tabular-nums" },
});

const COLUMNS: readonly DataTableColumn<CostRow>[] = [
  { key: "day", header: "Billing day", render: (r) => <Timestamp value={r.day} grain="day" /> },
  { key: "currency", header: "Currency", render: (r) => r.currency },
  {
    key: "est",
    header: "Estimated",
    render: (r) => formatCurrency(r.estimated, r.currency, { maximumFractionDigits: 0 }),
  },
  {
    key: "inv",
    header: "Invoiced",
    render: (r) => formatCurrency(r.invoiced, r.currency, { maximumFractionDigits: 0 }),
  },
  {
    key: "state",
    header: "Completeness",
    render: (r) =>
      r.complete ? (
        <StatusPill label="Complete" tone="success" />
      ) : (
        <StatusPill label="Incomplete" tone="warning" />
      ),
  },
];

function total(series: readonly { points: readonly { value: number | null }[] }[], i: number) {
  return (series[i]?.points ?? []).reduce((acc, p) => acc + (p.value ?? 0), 0);
}

export function CostMockup({
  styleId,
  mode,
}: {
  readonly styleId: UiStyleId;
  readonly mode: MockupMode;
}): ReactElement {
  const styles = useStyles();
  return (
    <MockupFrame styleId={styleId} mode={mode} active="Cost dashboard">
      <PageTemplate
        title="Cost dashboard"
        description="Estimated and invoiced cost per currency. Currencies are never summed or converted."
        actions={<Button appearance="secondary">Export CSV</Button>}
        kpis={
          <>
            <KpiCard
              label="USD estimated, 14 days"
              value={formatCurrency(total(USD_SERIES, 0), "USD", { maximumFractionDigits: 0 })}
            />
            <KpiCard
              label="USD invoiced, 14 days (partial)"
              value={formatCurrency(total(USD_SERIES, 1), "USD", { maximumFractionDigits: 0 })}
              status="degraded"
            />
            <KpiCard
              label="EUR estimated, 14 days"
              value={formatCurrency(total(EUR_SERIES, 0), "EUR", { maximumFractionDigits: 0 })}
            />
            <KpiCard
              label="EUR invoiced, 14 days (partial)"
              value={formatCurrency(total(EUR_SERIES, 1), "EUR", { maximumFractionDigits: 0 })}
              status="degraded"
            />
            <KpiCard
              label="Data freshness"
              value={<Timestamp value="2026-10-24T09:10:00Z" now={MOCKUP_NOW} />}
            />
            <KpiCard
              label="Analytics state"
              value="Live"
              status="ok"
              delta={{ text: "Fabric adapter", direction: "flat" }}
            />
          </>
        }
      >
        <div className={styles.charts}>
          <Panel title="Cost in USD" note={<HealthIndicator state="degraded" label="2 gaps" />}>
            <TimeSeriesChart series={USD_SERIES} variant="area" width={640} height={260} />
          </Panel>
          <Panel title="Cost in EUR" note={<HealthIndicator state="degraded" label="3 gaps" />}>
            <TimeSeriesChart series={EUR_SERIES} variant="area" width={640} height={260} />
          </Panel>
        </div>
        <Panel title="Daily detail, last 4 billing days" note="Absolute UTC dates">
          <DataTable
            label="Daily cost detail"
            columns={COLUMNS}
            rows={COST_ROWS}
            getRowId={(r) => `${r.day}-${r.currency}`}
          />
        </Panel>
      </PageTemplate>
    </MockupFrame>
  );
}
