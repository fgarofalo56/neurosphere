import { useCallback, useMemo } from "react";
import { useSearchParams } from "react-router";

/** Filter fields; each is also the URL search parameter and the PRP-74 query parameter name. */
export const FILTER_KEYS = ["node_type", "tag", "environment", "cloud", "health"] as const;
export type FilterKey = (typeof FILTER_KEYS)[number];

export type MapFilters = Readonly<Record<FilterKey, string>>;
/** Only the filters that are set; exactly the PRP-74 viewport/search query parameters. */
export type MapFilterQuery = Readonly<Partial<Record<FilterKey, string>>>;

/**
 * Server allowlists (services/api/neurosphere_api/map/service.py). A value outside them is a 422
 * `invalid_filter`, so a hand-edited URL is dropped here instead of sent.
 */
export const ALLOWED_VALUES: Readonly<Record<Exclude<FilterKey, "tag">, readonly string[]>> = {
  node_type: ["person", "agent", "model", "source", "service", "tool", "mcp_server"],
  environment: ["production", "staging", "development", "test", "sandbox", "unknown"],
  cloud: ["commercial", "government"],
  health: ["ok", "degraded", "failing", "unknown"],
};

/** The PRP-70 tag grammar: catalog/v1 common.schema.json `$defs/tag`. */
export const TAG_PATTERN = /^[a-z0-9][a-z0-9._-]{0,62}$/;

export function isValidTag(value: string): boolean {
  return TAG_PATTERN.test(value);
}

export function isValidFilterValue(key: FilterKey, value: string): boolean {
  if (value === "") return false;
  return key === "tag" ? isValidTag(value) : ALLOWED_VALUES[key].includes(value);
}

export const EMPTY_FILTERS: MapFilters = {
  node_type: "",
  tag: "",
  environment: "",
  cloud: "",
  health: "",
};

/** Reads and validates the filters out of a query string; invalid values read as unset. */
export function readFilters(params: URLSearchParams): MapFilters {
  const out: Record<FilterKey, string> = { ...EMPTY_FILTERS };
  for (const key of FILTER_KEYS) {
    const value = params.get(key) ?? "";
    if (isValidFilterValue(key, value)) out[key] = value;
  }
  return out;
}

export function filtersToQuery(filters: MapFilters): MapFilterQuery {
  const out: Partial<Record<FilterKey, string>> = {};
  for (const key of FILTER_KEYS) {
    if (filters[key] !== "") out[key] = filters[key];
  }
  return out;
}

export interface UseMapFilters {
  readonly filters: MapFilters;
  /** Sets one filter ("" clears it). Returns false, changing nothing, when the value is invalid. */
  setFilter(key: FilterKey, value: string): boolean;
  clearAll(): void;
  readonly activeCount: number;
  /** The PRP-74 query parameters for the filters that are set. Stable while they do not change. */
  toQuery(): MapFilterQuery;
  /** Stable string identity of the active filters (for resetting state on change). */
  readonly signature: string;
}

/**
 * Filter state in the URL search params, so a filtered view is shareable, survives reload and the
 * back button restores the previous filter. Shared by the map and the table. Other parameters
 * (such as `domain_id`) are preserved.
 */
export function useMapFilters(): UseMapFilters {
  const [params, setParams] = useSearchParams();
  const search = params.toString();
  const filters = useMemo(() => readFilters(new URLSearchParams(search)), [search]);
  const query = useMemo(() => filtersToQuery(filters), [filters]);
  const signature = useMemo(() => JSON.stringify(query), [query]);
  const activeCount = Object.keys(query).length;

  const setFilter = useCallback(
    (name: FilterKey, value: string): boolean => {
      if (value !== "" && !isValidFilterValue(name, value)) return false;
      setParams((prev) => {
        const next = new URLSearchParams(prev);
        if (value === "") next.delete(name);
        else next.set(name, value);
        return next;
      });
      return true;
    },
    [setParams],
  );

  const clearAll = useCallback(() => {
    setParams((prev) => {
      const next = new URLSearchParams(prev);
      for (const name of FILTER_KEYS) next.delete(name);
      return next;
    });
  }, [setParams]);

  const toQuery = useCallback(() => query, [query]);

  return { filters, setFilter, clearAll, activeCount, toQuery, signature };
}
