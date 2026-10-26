import type { ReactElement } from "react";
import { StatePanel } from "./StatePanel";

export interface ForbiddenStateProps {
  readonly workspace: string;
  readonly correlationId?: string | undefined;
}

/**
 * Shown when the API answers 403. The copy only reports what the server said; it does
 * not claim the UI enforces anything (the API is the sole enforcement point).
 */
export function ForbiddenState({ workspace, correlationId }: ForbiddenStateProps): ReactElement {
  return (
    <StatePanel tone="warning" title="Access denied" data-testid="forbidden-state">
      The service declined the request for the {workspace} workspace. If you need access, contact
      your administrator.
      {correlationId !== undefined && correlationId !== "" ? ` Reference: ${correlationId}.` : ""}
    </StatePanel>
  );
}
