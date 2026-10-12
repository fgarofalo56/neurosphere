import { MessageBar, MessageBarBody, MessageBarTitle } from "@fluentui/react-components";
import type { ReactElement } from "react";
import { ForbiddenError, createQueryHook } from "../../api/index.js";
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
  const heading = <h1>{label}</h1>;

  if (query.isError) {
    const error = query.error;
    if (error instanceof ForbiddenError) {
      return (
        <section aria-label={label}>
          {heading}
          <ForbiddenState workspace={def.label} correlationId={error.correlationId} />
        </section>
      );
    }
    return (
      <section aria-label={label}>
        {heading}
        <MessageBar intent="error" role="alert" data-testid="error-state">
          <MessageBarBody>
            <MessageBarTitle>Could not load this workspace</MessageBarTitle>
            The request failed
            {error.correlationId !== "" ? ` (reference ${error.correlationId})` : ""}. This is not
            an empty result. Try again later.
          </MessageBarBody>
        </MessageBar>
      </section>
    );
  }

  if (query.isPending) {
    return (
      <section aria-label={label} aria-busy="true">
        {heading}
        <p>Loading...</p>
      </section>
    );
  }

  return (
    <section aria-label={label}>
      {heading}
      <p>{def.description}</p>
      <p>Placeholder: this workspace is built out in later work.</p>
    </section>
  );
}
