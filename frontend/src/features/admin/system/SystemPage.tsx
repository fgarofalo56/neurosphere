import type { ReactElement } from "react";
import {
  DataTable,
  EmptyState,
  LoadingState,
  PageTemplate,
  Panel,
  StatusPill,
  type StatusTone,
} from "../../../design-system";
import { AdminTabs } from "../shared/AdminTabs";
import { QueryErrorState } from "../shared/AdminStates";
import {
  asList,
  useChecklist,
  useSettings,
  useSystemStatus,
  type ChecklistStatus,
  type ComponentState,
} from "../shared/systemHooks";
import { SYSTEM_STRINGS as S } from "./strings";

const COMPONENT_TONE: Record<ComponentState, StatusTone> = {
  ok: "success",
  failed: "danger",
  disabled: "neutral",
  not_built: "neutral",
};

const CHECKLIST_TONE: Record<ChecklistStatus, StatusTone> = {
  complete: "success",
  missing: "warning",
  error: "danger",
  disabled: "neutral",
  not_applicable: "neutral",
};

function Loading({ label }: { readonly label: string }): ReactElement {
  return (
    <div aria-busy="true" data-testid="loading-state">
      <LoadingState label={label} rows={3} />
    </div>
  );
}

/** Reasons are codes from the API (never a host or a secret); they render as the code. */
function Reason({ value }: { readonly value: string | null }): ReactElement {
  return value === null ? <span>{S.noReason}</span> : <code>{value}</code>;
}

function ComponentsPanel(): ReactElement {
  const query = useSystemStatus({});
  if (query.isError) {
    return <QueryErrorState error={query.error} onRetry={() => void query.refetch()} />;
  }
  if (query.isPending) return <Loading label={S.loadingStatus} />;
  const components = asList(query.data.components);
  return (
    <>
      <p data-testid="ready-state">{query.data.ready ? S.ready : S.notReady}</p>
      <p data-testid="stored-settings-state">
        {S.storedSettings(query.data.stored_settings?.status ?? "unknown")}
      </p>
      {components.length === 0 ? (
        <div data-testid="empty-state">
          <EmptyState title={S.noComponents} />
        </div>
      ) : (
        <DataTable
          label={S.componentsTitle}
          rows={components}
          getRowId={(row) => row.name}
          getRowProps={() => ({ "data-testid": "component-row" })}
          columns={[
            { key: "name", header: S.headers.component, render: (row) => row.name },
            {
              key: "state",
              header: S.headers.state,
              render: (row) => (
                <StatusPill label={S.componentState[row.state]} tone={COMPONENT_TONE[row.state]} />
              ),
            },
            {
              key: "required",
              header: S.headers.required,
              render: (row) => (row.required ? S.yes : S.no),
            },
            {
              key: "reason",
              header: S.headers.reason,
              render: (row) => <Reason value={row.reason} />,
            },
          ]}
        />
      )}
    </>
  );
}

function ChecklistPanel(): ReactElement {
  const query = useChecklist({});
  if (query.isError) {
    return <QueryErrorState error={query.error} onRetry={() => void query.refetch()} />;
  }
  if (query.isPending) return <Loading label={S.loadingChecklist} />;
  const items = asList(query.data.items);
  if (items.length === 0) {
    return (
      <div data-testid="empty-state">
        <EmptyState title={S.noChecklist} />
      </div>
    );
  }
  return (
    <DataTable
      label={S.checklistTitle}
      rows={items}
      getRowId={(row) => row.item_id}
      getRowProps={() => ({ "data-testid": "checklist-row" })}
      columns={[
        { key: "item", header: S.headers.item, render: (row) => row.item_id },
        { key: "component", header: S.headers.component, render: (row) => row.component },
        {
          key: "status",
          header: S.headers.status,
          render: (row) => (
            <StatusPill label={S.checklistStatus[row.status]} tone={CHECKLIST_TONE[row.status]} />
          ),
        },
        { key: "reason", header: S.headers.reason, render: (row) => <Reason value={row.reason} /> },
        {
          key: "docs",
          header: S.headers.docs,
          render: (row) => (row.doc_path === null ? S.noReason : <code>{row.doc_path}</code>),
        },
      ]}
    />
  );
}

function SettingsPanel(): ReactElement {
  const query = useSettings({});
  if (query.isError) {
    return <QueryErrorState error={query.error} onRetry={() => void query.refetch()} />;
  }
  if (query.isPending) return <Loading label={S.loadingSettings} />;
  const items = asList(query.data.items);
  if (items.length === 0) {
    return (
      <div data-testid="empty-state">
        <EmptyState title={S.noSettings} />
      </div>
    );
  }
  return (
    <DataTable
      label={S.settingsTitle}
      rows={items}
      getRowId={(row) => row.key}
      getRowProps={() => ({ "data-testid": "setting-row" })}
      columns={[
        { key: "key", header: S.headers.key, render: (row) => row.key },
        { key: "source", header: S.headers.source, render: (row) => S.source[row.source] },
        {
          key: "restart",
          header: S.headers.restart,
          render: (row) =>
            row.restart_required ? <StatusPill label={S.restartRequired} tone="warning" /> : S.no,
        },
      ]}
    />
  );
}

/**
 * System status (PRP-45). Only the fields named in `systemHooks` are read: a configuration value,
 * host or secret that a response carries is never rendered. Editing stored settings is PRP-57.
 */
export function SystemPage(): ReactElement {
  return (
    <PageTemplate title={S.title} description={S.description} layout="stack">
      <AdminTabs />
      <Panel title={S.componentsTitle}>
        <ComponentsPanel />
      </Panel>
      <Panel title={S.checklistTitle}>
        <ChecklistPanel />
      </Panel>
      <Panel title={S.settingsTitle}>
        <p>{S.settingsNote}</p>
        <SettingsPanel />
      </Panel>
    </PageTemplate>
  );
}
