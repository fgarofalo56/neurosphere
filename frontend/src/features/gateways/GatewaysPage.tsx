import type { ReactElement } from "react";
import { useSelectedDomain } from "../../app/domain";
import { EmptyState, LoadingState, PageTemplate } from "../../design-system";
import { EmergencyBanner, QueryErrorState } from "../actions/components";
import { GatewayModePanel } from "./GatewayModePanel";
import { useGateways } from "./hooks";
import { STRINGS } from "./strings";

function Body({ domainId }: { readonly domainId: string }): ReactElement {
  const query = useGateways({ domainId });
  if (query.isError) {
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
        <LoadingState label={STRINGS.loading} rows={4} />
      </div>
    );
  }
  if (query.data.items.length === 0) {
    return (
      <div data-testid="empty-state">
        <EmptyState title={STRINGS.empty} />
      </div>
    );
  }
  return (
    <>
      {query.data.items.map((gateway) => (
        <GatewayModePanel key={gateway.id} domainId={domainId} gateway={gateway} />
      ))}
    </>
  );
}

/** Registered gateways of the selected domain with the audited observe/manage switch. */
export function GatewaysPage(): ReactElement {
  const { domainId } = useSelectedDomain();
  return (
    <PageTemplate title={STRINGS.title} description={STRINGS.description}>
      <EmergencyBanner />
      {domainId === "" ? (
        <div data-testid="domain-required">
          <EmptyState title={STRINGS.domainRequired} />
        </div>
      ) : (
        <Body key={domainId} domainId={domainId} />
      )}
    </PageTemplate>
  );
}
