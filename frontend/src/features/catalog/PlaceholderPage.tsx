import { Text } from "@fluentui/react-components";
import type { ReactElement } from "react";
import { PageTemplate } from "../../design-system";
import { EXPLORER_STRINGS } from "./explorerStrings";

type PageKey = "explorer" | "entity" | "recertifications" | "staleAgents";

function Placeholder({ page }: { readonly page: PageKey }): ReactElement {
  const s = EXPLORER_STRINGS[page];
  return (
    <PageTemplate title={s.title} description={s.description}>
      <Text>{EXPLORER_STRINGS.placeholder}</Text>
    </PageTemplate>
  );
}

/** Item 1 placeholders; the catalog lane replaces them with the real pages. */
export const CatalogExplorerPlaceholderPage = (): ReactElement => <Placeholder page="explorer" />;
export const CatalogEntityPlaceholderPage = (): ReactElement => <Placeholder page="entity" />;
export const RecertificationsPlaceholderPage = (): ReactElement => (
  <Placeholder page="recertifications" />
);
export const StaleAgentsPlaceholderPage = (): ReactElement => <Placeholder page="staleAgents" />;
