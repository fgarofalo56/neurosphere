import { Text } from "@fluentui/react-components";
import type { ReactElement } from "react";
import { PageTemplate } from "../../design-system";
import { STRINGS } from "./strings";

/** Item 1 placeholders; the deploy lane replaces them with the real pages. */
export function DeployPlaceholderPage(): ReactElement {
  return (
    <PageTemplate title={STRINGS.pageTitle} description={STRINGS.pageDescription}>
      <Text>{STRINGS.placeholder}</Text>
    </PageTemplate>
  );
}

export function CapabilitiesPlaceholderPage(): ReactElement {
  return (
    <PageTemplate title={STRINGS.capabilitiesTitle} description={STRINGS.capabilitiesDescription}>
      <Text>{STRINGS.placeholder}</Text>
    </PageTemplate>
  );
}
