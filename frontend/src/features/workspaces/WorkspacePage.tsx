import type { ReactElement } from "react";
import { ForbiddenError, createQueryHook } from "../../api/index.js";
import {
  ErrorState,
  HealthIndicator,
  LoadingState,
  PageTemplate,
  Panel,
  StatusPill,
} from "../../design-system";
import { ForbiddenState } from "./ForbiddenState";
import { probePath, type WorkspaceDef } from "./personas";

const useWorkspaceProbe = createQueryHook<{ path: string }, unknown>({
  key: "workspace-probe",
  fetcher: (client, params, signal) => client.get<unknown>(params.path, undefined, signal),
});

/** The probe is issued on every mount, even when navigation to this page was hidden. */
export function WorkspacePage({ def }: { readonly def: WorkspaceDef }): ReactElement {
  const query = useWorkspaceProbe({ path: probePath(def.persona) });
  const label = `${def.label} workspace`;

  if (query.isError) {
    const error = query.error;
    if (error instanceof ForbiddenError) {
      return (
        <PageTemplate title={label}>
          <ForbiddenState workspace={def.label} correlationId={error.correlationId} />
        </PageTemplate>
      );
    }
    return (
      <PageTemplate title={label}>
        <ErrorState
          title="Could not load this workspace"
          testId="error-state"
          message={
            <>
              The request failed
              {error.correlationId !== "" ? ` (reference ${error.correlationId})` : ""}. This is not
              an empty result. Try again later.
            </>
          }
        />
      </PageTemplate>
    );
  }

  if (query.isPending) {
    return (
      <PageTemplate title={label} busy>
        <LoadingState label={`Loading the ${label}`} rows={4} />
      </PageTemplate>
    );
  }

  return (
    <PageTemplate title={label} layout="grid">
      <Panel title="Purpose">
        <p>{def.description}</p>
        <div>
          <StatusPill label={def.persona} tone="neutral" />
        </div>
      </Panel>
      <Panel title="Service status">
        <div>
          <HealthIndicator state="ok" label="Service answered" />
        </div>
        <p>Placeholder: this workspace is built out in later work.</p>
      </Panel>
    </PageTemplate>
  );
}
