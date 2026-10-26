import { MessageBar, MessageBarBody } from "@fluentui/react-components";
import type { ReactElement } from "react";
import { AppThemeProvider } from "../../design-system";

/**
 * Persistent local-demo notice. An in-flow strip at the top of the page (like the sandbox
 * banner), never a fixed overlay, so it cannot cover the copilot launcher or page content.
 */
export function DemoBanner(): ReactElement {
  return (
    <AppThemeProvider>
      <div data-testid="demo-banner">
        <MessageBar intent="warning" layout="singleline">
          <MessageBarBody>
            <strong>Demo data, mock API</strong> - local demo only, nothing here is real tenant
            data.
          </MessageBarBody>
        </MessageBar>
      </div>
    </AppThemeProvider>
  );
}
