import { MessageBar, MessageBarBody } from "@fluentui/react-components";
import type { ReactElement } from "react";
import { AppThemeProvider } from "../../design-system";

/** Persistent local-demo notice. Fixed to the viewport so it shows on every page. */
export function DemoBanner(): ReactElement {
  return (
    <AppThemeProvider>
      <div
        data-testid="demo-banner"
        style={{ position: "fixed", left: 0, right: 0, bottom: 0, zIndex: 2147483000 }}
      >
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
