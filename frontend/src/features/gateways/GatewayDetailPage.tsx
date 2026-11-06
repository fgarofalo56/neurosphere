import type { ReactElement } from "react";
import { Link, useSearchParams } from "react-router";
import { useSelectedDomain } from "../../app/domain";
import {
  DataTable,
  EmptyState,
  LoadingState,
  PageTemplate,
  Panel,
  StatusPill,
  Timestamp,
} from "../../design-system";
import { EmergencyBanner, QueryErrorState } from "../actions/components";
import { GatewayObserveSummary } from "./GatewayObserveSummary";
import { useGatewayDetail, useGatewayInventory } from "./hooks";
import { GATEWAYS_ROUTE } from "./paths";
import { STRINGS } from "./strings";
import type { BackendEntry, GatewayInventory, GatewayRegistration } from "./types";

const D = STRINGS.detail;
const C = D.cols;

function yesNo(value: boolean | null | undefined): string {
  return value === undefined || value === null ? "" : value ? D.yes : D.no;
}

function text(value: string | null | undefined): string {
  return value === undefined || value === null ? "" : value;
}

function Section<T>({
  title,
  testId,
  rows,
  getRowId,
  columns,
}: {
  readonly title: string;
  readonly testId: string;
  readonly rows: readonly T[];
  readonly getRowId: (row: T) => string;
  readonly columns: readonly {
    readonly key: string;
    readonly header: string;
    readonly render: (row: T) => ReactElement | string;
  }[];
}): ReactElement {
  return (
    <Panel title={`${title} (${String(rows.length)})`} testId={testId}>
      {rows.length === 0 ? (
        <EmptyState title={D.emptyTable} />
      ) : (
        <DataTable
          label={title}
          rows={rows}
          getRowId={getRowId}
          getRowProps={() => ({ "data-testid": `${testId}-row` })}
          columns={columns}
        />
      )}
    </Panel>
  );
}

function PoolMembers({ backend }: { readonly backend: BackendEntry }): ReactElement {
  const members = backend.pool_members ?? [];
  return (
    <>
      {members.length === 0 ? D.none : null}
      {members.map((m) => (
        <div key={m.backend_id} data-testid="pool-member">
          {m.backend_id}
          {m.weight === undefined || m.weight === null
            ? ""
            : ` (${C.weight} ${String(m.weight)}${
                m.priority === undefined || m.priority === null
                  ? ""
                  : `, ${C.priority} ${String(m.priority)}`
              })`}
        </div>
      ))}
    </>
  );
}

function CircuitBreakers({ backend }: { readonly backend: BackendEntry }): ReactElement {
  const rules = backend.circuit_breaker_rules ?? [];
  if (rules.length === 0) return <>{D.none}</>;
  return (
    <>
      {rules.map((r, i) => (
        <div key={`${text(r.name)}-${String(i)}`} data-testid="circuit-breaker">
          {text(r.name)}
          {r.failure_count === undefined || r.failure_count === null
            ? ""
            : ` ${String(r.failure_count)} ${C.failures}`}
          {r.trip_duration === undefined || r.trip_duration === null
            ? ""
            : `, ${C.trips} ${r.trip_duration}`}
          {r.status_codes === undefined || r.status_codes.length === 0
            ? ""
            : ` [${r.status_codes.join(", ")}]`}
        </div>
      ))}
    </>
  );
}

function InventoryTables({ inventory }: { readonly inventory: GatewayInventory }): ReactElement {
  return (
    <>
      <p data-testid="inventory-taken-at">
        {D.inventoryTakenAt}: <Timestamp value={inventory.taken_at} />
      </p>
      <Section
        title={D.apis}
        testId="inventory-apis"
        rows={inventory.apis}
        getRowId={(a) => a.id}
        columns={[
          { key: "id", header: C.id, render: (a) => a.id },
          { key: "name", header: C.name, render: (a) => text(a.name) },
          { key: "path", header: C.path, render: (a) => text(a.path) },
          { key: "protocols", header: C.protocols, render: (a) => (a.protocols ?? []).join(", ") },
          {
            key: "sub",
            header: C.subscriptionRequired,
            render: (a) => yesNo(a.subscription_required),
          },
        ]}
      />
      <Section
        title={D.operations}
        testId="inventory-operations"
        rows={inventory.operations}
        getRowId={(o) => `${o.api_id}/${o.id}`}
        columns={[
          { key: "api", header: D.apis, render: (o) => o.api_id },
          { key: "id", header: C.id, render: (o) => o.id },
          { key: "method", header: "Method", render: (o) => text(o.method) },
          { key: "tpl", header: "URL template", render: (o) => text(o.url_template) },
        ]}
      />
      <Section
        title={D.products}
        testId="inventory-products"
        rows={inventory.products}
        getRowId={(p) => p.id}
        columns={[
          { key: "id", header: C.id, render: (p) => p.id },
          { key: "name", header: C.name, render: (p) => text(p.name) },
          { key: "state", header: C.state, render: (p) => text(p.state) },
          {
            key: "sub",
            header: C.subscriptionRequired,
            render: (p) => yesNo(p.subscription_required),
          },
          { key: "appr", header: C.approvalRequired, render: (p) => yesNo(p.approval_required) },
        ]}
      />
      <Section
        title={D.backends}
        testId="inventory-backends"
        rows={inventory.backends}
        getRowId={(b) => b.id}
        columns={[
          { key: "id", header: C.id, render: (b) => b.id },
          { key: "type", header: C.type, render: (b) => b.type },
          { key: "url", header: C.url, render: (b) => text(b.url) },
          {
            key: "members",
            header: C.poolMembers,
            render: (b) => <PoolMembers backend={b} />,
          },
          {
            key: "breakers",
            header: C.circuitBreakers,
            render: (b) => <CircuitBreakers backend={b} />,
          },
        ]}
      />
      <Section
        title={D.policyFragments}
        testId="inventory-fragments"
        rows={inventory.policy_fragments}
        getRowId={(f) => f.name}
        columns={[
          { key: "name", header: C.name, render: (f) => f.name },
          { key: "desc", header: C.description, render: (f) => text(f.description) },
        ]}
      />
      <Section
        title={D.subscriptions}
        testId="inventory-subscriptions"
        rows={inventory.subscriptions}
        getRowId={(s) => s.id}
        columns={[
          { key: "id", header: C.id, render: (s) => s.id },
          { key: "name", header: C.displayName, render: (s) => text(s.display_name) },
          { key: "scope", header: C.scope, render: (s) => text(s.scope) },
          { key: "state", header: C.state, render: (s) => text(s.state) },
        ]}
      />
    </>
  );
}

function Inventory({
  domainId,
  gatewayId,
}: {
  readonly domainId: string;
  readonly gatewayId: string;
}): ReactElement {
  const query = useGatewayInventory({ domainId, gatewayId });
  if (query.isError) {
    // No snapshot yet is a 404 on the inventory: say so instead of showing a failure.
    if (query.error.status === 404) {
      return (
        <div data-testid="inventory-empty">
          <EmptyState title={D.noInventory} />
        </div>
      );
    }
    return (
      <QueryErrorState
        error={query.error}
        onRetry={() => {
          void query.refetch();
        }}
      />
    );
  }
  if (query.isPending) {
    return (
      <div aria-busy="true" data-testid="inventory-loading">
        <LoadingState label={D.inventoryLoading} rows={4} />
      </div>
    );
  }
  return <InventoryTables inventory={query.data} />;
}

function Overview({
  domainId,
  gateway,
}: {
  readonly domainId: string;
  readonly gateway: GatewayRegistration;
}): ReactElement {
  return (
    <Panel title={gateway.name} testId="gateway-detail">
      <dl>
        <dt>{STRINGS.mode.label}</dt>
        <dd data-testid="gateway-mode">
          <StatusPill
            label={gateway.mode === "manage" ? STRINGS.mode.manage : STRINGS.mode.observe}
            tone={gateway.mode === "manage" ? "warning" : "info"}
          />
        </dd>
        <dt>{D.cloud}</dt>
        <dd>{gateway.cloud}</dd>
        {gateway.arm_resource_id === undefined ? null : (
          <>
            <dt>{D.armId}</dt>
            <dd>
              <code>{gateway.arm_resource_id}</code>
            </dd>
          </>
        )}
      </dl>
      <GatewayObserveSummary domainId={domainId} gateway={gateway} />
    </Panel>
  );
}

function Body({
  domainId,
  gatewayId,
}: {
  readonly domainId: string;
  readonly gatewayId: string;
}): ReactElement {
  const query = useGatewayDetail({ domainId, gatewayId });
  if (query.isError) {
    if (query.error.status === 404) {
      return (
        <div data-testid="gateway-not-found">
          <EmptyState title={D.notFound} />
        </div>
      );
    }
    return (
      <QueryErrorState
        error={query.error}
        onRetry={() => {
          void query.refetch();
        }}
      />
    );
  }
  if (query.isPending) {
    return (
      <div aria-busy="true" data-testid="loading-state">
        <LoadingState label={D.loading} rows={3} />
      </div>
    );
  }
  return (
    <>
      <Overview domainId={domainId} gateway={query.data} />
      <Inventory domainId={domainId} gatewayId={gatewayId} />
    </>
  );
}

/** Read-only gateway detail: the registration summary plus the latest inventory snapshot. */
export function GatewayDetailPage(): ReactElement {
  const { domainId } = useSelectedDomain();
  const [params] = useSearchParams();
  const gatewayId = params.get("gateway_id") ?? "";
  return (
    <PageTemplate
      title={D.title}
      description={D.description}
      actions={<Link to={`/${GATEWAYS_ROUTE}`}>{D.back}</Link>}
    >
      <EmergencyBanner />
      {domainId === "" ? (
        <div data-testid="domain-required">
          <EmptyState title={STRINGS.domainRequired} />
        </div>
      ) : gatewayId === "" ? (
        <div data-testid="gateway-required">
          <EmptyState title={D.idRequired} />
        </div>
      ) : (
        <Body key={`${domainId}/${gatewayId}`} domainId={domainId} gatewayId={gatewayId} />
      )}
    </PageTemplate>
  );
}
