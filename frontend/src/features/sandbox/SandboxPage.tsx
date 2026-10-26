import { Button } from "@fluentui/react-components";
import type { ReactElement } from "react";
import { ForbiddenError } from "../../api/index.js";
import {
  EmptyState,
  KpiCard,
  LoadingState,
  PageTemplate,
  StatusPill,
  formatNumber,
} from "../../design-system";
import { Panel } from "../workspaces/Panel";
import { RowTable } from "../workspaces/RowTable";
import { StatePanel } from "../workspaces/StatePanel";
import { useSandboxStatus } from "./hooks";
import { SandboxToggle } from "./SandboxToggle";
import { STRINGS } from "./strings";

const NO_PARAMS: Record<string, never> = {};

function kindLabel(kind: string): string {
  return kind in STRINGS.kinds ? STRINGS.kinds[kind as keyof typeof STRINGS.kinds] : kind;
}

export function SandboxPage(): ReactElement {
  const query = useSandboxStatus(NO_PARAMS);

  if (query.isError) {
    const forbidden = query.error instanceof ForbiddenError;
    return (
      <PageTemplate
        title={STRINGS.pageTitle}
        description={STRINGS.pageDescription}
        actions={<SandboxToggle />}
      >
        <StatePanel
          tone="warning"
          title={forbidden ? STRINGS.forbidden : STRINGS.unavailable}
          data-testid="sandbox-error"
          action={
            forbidden ? undefined : (
              <Button onClick={() => void query.refetch()}>{STRINGS.retry}</Button>
            )
          }
        >
          {forbidden ? STRINGS.forbiddenDetail : STRINGS.unavailableDetail}
        </StatePanel>
      </PageTemplate>
    );
  }

  if (query.isPending) {
    return (
      <PageTemplate
        title={STRINGS.pageTitle}
        description={STRINGS.pageDescription}
        actions={<SandboxToggle />}
        busy
      >
        <LoadingState label={STRINGS.loading} rows={4} />
      </PageTemplate>
    );
  }

  const data = query.data;
  const entries = Object.entries(data.counts);
  return (
    <PageTemplate
      title={STRINGS.pageTitle}
      description={STRINGS.pageDescription}
      actions={<SandboxToggle />}
      kpis={
        <>
          <KpiCard
            label={STRINGS.total}
            value={<span data-testid="sandbox-total">{formatNumber(data.total)}</span>}
          />
          <KpiCard label={STRINGS.relations} value={formatNumber(data.relations)} />
        </>
      }
      layout="split"
    >
      <Panel title={STRINGS.environment}>
        <dl data-testid="sandbox-flags">
          <dt>{STRINGS.environment}</dt>
          <dd>{data.environment}</dd>
          <dt>{STRINGS.synthetic}</dt>
          <dd>{data.synthetic ? <StatusPill label={STRINGS.yes} tone="success" /> : ""}</dd>
        </dl>
      </Panel>
      <Panel title={STRINGS.pageTitle}>
        {entries.length === 0 ? (
          <EmptyState title="The sandbox holds no documents" />
        ) : (
          <RowTable
            label={STRINGS.pageTitle}
            rows={entries}
            getRowId={([kind]) => kind}
            rowTestId="sandbox-row"
            columns={[
              { key: "kind", header: STRINGS.headers.kind, render: ([kind]) => kindLabel(kind) },
              {
                key: "count",
                header: STRINGS.headers.count,
                render: ([, count]) => formatNumber(count),
              },
            ]}
          />
        )}
      </Panel>
    </PageTemplate>
  );
}
