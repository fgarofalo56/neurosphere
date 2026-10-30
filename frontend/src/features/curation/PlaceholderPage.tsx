import { Text } from "@fluentui/react-components";
import type { ReactElement } from "react";
import { PageTemplate } from "../../design-system";
import { STRINGS } from "./strings";

/** Item 1 placeholder; the lane that owns this folder replaces it with the real page. */
export function CurationPlaceholderPage(): ReactElement {
  return (
    <PageTemplate title={STRINGS.pageTitle} description={STRINGS.pageDescription}>
      <Text>{STRINGS.placeholder}</Text>
    </PageTemplate>
  );
}
