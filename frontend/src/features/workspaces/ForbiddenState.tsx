import { MessageBar, MessageBarBody, MessageBarTitle } from "@fluentui/react-components";
import type { ReactElement } from "react";

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
    <MessageBar intent="warning" role="alert" data-testid="forbidden-state">
      <MessageBarBody>
        <MessageBarTitle>Access denied</MessageBarTitle>
        The service declined the request for the {workspace} workspace. If you need access, contact
        your administrator.
        {correlationId !== undefined && correlationId !== "" ? ` Reference: ${correlationId}.` : ""}
      </MessageBarBody>
    </MessageBar>
  );
}
