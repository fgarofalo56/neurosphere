import { useAdminGet, useEtagMutation } from "../shared/transport";
import { pricingPaths } from "../sources/apiPaths";

export const PRICE_SHEETS_KEY = "admin-price-sheets";
export const BUDGETS_KEY = "admin-budgets";

export interface PriceSheetView {
  readonly snapshot_id: string;
  readonly source: string;
  readonly source_url: string;
  readonly retrieval_date: string;
  readonly effective_date: string;
  readonly currency: string;
  readonly clouds: readonly string[];
  readonly synthetic: boolean;
  readonly content_hash: string;
  readonly row_count: number;
  readonly notes: string;
}
export interface PriceSheetPage {
  readonly items: readonly PriceSheetView[];
}
export interface CoverageView {
  readonly snapshot_id: string;
  readonly rows: number;
  readonly models_priced: number;
  readonly models_incomplete: readonly {
    readonly provider: string;
    readonly model: string;
    readonly model_version: string | null;
    readonly missing: readonly string[];
  }[];
  readonly rows_without_token_meter: number;
  readonly warnings: readonly string[];
}
export interface PriceSheetUploadView {
  readonly sheet: PriceSheetView;
  readonly coverage: CoverageView;
  readonly created: boolean;
}
export interface PriceSheetBody {
  readonly schema_version: "1.0.0";
  readonly snapshot_id: string;
  readonly source: string;
  readonly source_url: string;
  readonly retrieval_date: string;
  readonly effective_date: string;
  readonly currency: string;
  readonly clouds: readonly string[];
  readonly synthetic: boolean;
  readonly notes: string;
  readonly rows: readonly Record<string, unknown>[];
}

export interface BudgetView {
  readonly budget_id: string;
  readonly domain_id: string;
  readonly period: "monthly" | "quarterly" | "annual";
  readonly amount: string;
  readonly currency: string;
  readonly thresholds_percent: readonly number[];
  readonly tags_filter: Readonly<Record<string, string>> | null;
  readonly status: string;
  readonly version: number;
  readonly updated_at: string;
  readonly updated_by: string;
}
export interface BudgetPage {
  readonly items: readonly BudgetView[];
}
export interface BudgetBody {
  readonly schema_version: "1.0.0";
  readonly budget_id: string;
  readonly domain_id: string;
  readonly period: string;
  readonly amount: string;
  readonly currency: string;
  readonly thresholds_percent: readonly number[];
}

export function usePriceSheets() {
  return useAdminGet<PriceSheetPage>(PRICE_SHEETS_KEY, { path: pricingPaths.priceSheets() });
}

export function useUploadPriceSheet() {
  return useEtagMutation<PriceSheetBody, PriceSheetUploadView>((body) => ({
    method: "POST",
    path: pricingPaths.priceSheets(),
    body,
  }));
}

export function useBudgets() {
  return useAdminGet<BudgetPage>(BUDGETS_KEY, {
    path: pricingPaths.budgets(),
    query: { include_retired: false, limit: 200 },
  });
}

export function useReadBudget() {
  return useEtagMutation<string, BudgetView>((id) => ({
    method: "GET",
    path: pricingPaths.budget(id),
  }));
}

export function useCreateBudget() {
  return useEtagMutation<BudgetBody, BudgetView>((body) => ({
    method: "POST",
    path: pricingPaths.budgets(),
    body,
  }));
}

export function useReplaceBudget() {
  return useEtagMutation<
    { readonly body: BudgetBody; readonly etag: string | undefined },
    BudgetView
  >((v) => ({
    method: "PUT",
    path: pricingPaths.budget(v.body.budget_id),
    body: v.body,
    ifMatch: v.etag,
  }));
}

export function useRetireBudget() {
  return useEtagMutation<
    { readonly budgetId: string; readonly etag: string | undefined },
    BudgetView
  >((v) => ({ method: "DELETE", path: pricingPaths.budget(v.budgetId), ifMatch: v.etag }));
}
