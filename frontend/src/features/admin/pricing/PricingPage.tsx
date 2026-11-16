import type { ReactElement } from "react";
import { PageTemplate } from "../../../design-system";
import { AdminTabs } from "../shared/AdminTabs";
import { BudgetsPanel } from "./BudgetsPanel";
import { PriceSheetsPanel } from "./PriceSheetsPanel";

export const PRICING_STRINGS = {
  title: "Pricing and budgets",
  description:
    "Upload versioned price sheets and set spend budgets per domain. Amounts are decimal strings; an unknown price is shown as unknown, never as zero.",
} as const;

export function PricingPage(): ReactElement {
  return (
    <PageTemplate title={PRICING_STRINGS.title} description={PRICING_STRINGS.description}>
      <AdminTabs />
      <PriceSheetsPanel />
      <BudgetsPanel />
    </PageTemplate>
  );
}
