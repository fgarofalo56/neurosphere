import { Button, Field, Input, Select, makeStyles, tokens } from "@fluentui/react-components";
import { useEffect, useState, type FormEvent, type ReactElement } from "react";
import { kindLabel } from "../strings";
import { countsOf, useFilterCounts } from "./hooks";
import { FILTER_STRINGS as S } from "./strings";
import { ALLOWED_VALUES, isValidTag, type FilterKey, type UseMapFilters } from "./useMapFilters";

const useStyles = makeStyles({
  bar: {
    display: "flex",
    flexWrap: "wrap",
    alignItems: "flex-end",
    gap: tokens.spacingHorizontalM,
  },
  tagForm: { display: "flex", alignItems: "flex-end", gap: tokens.spacingHorizontalXS },
  muted: { color: tokens.colorNeutralForeground2, fontSize: tokens.fontSizeBase200 },
});

type SelectKey = Exclude<FilterKey, "tag">;

const SELECTS: readonly {
  readonly key: SelectKey;
  readonly label: string;
  readonly counts: "by_kind" | "by_environment" | "by_cloud" | "by_health";
}[] = [
  { key: "node_type", label: S.nodeType, counts: "by_kind" },
  { key: "environment", label: S.environment, counts: "by_environment" },
  { key: "cloud", label: S.cloud, counts: "by_cloud" },
  { key: "health", label: S.health, counts: "by_health" },
];

export interface FilterBarProps {
  readonly domainId: string;
  readonly state: UseMapFilters;
}

/**
 * Filter controls for the map (and, later, the table). Every control is a labelled form control
 * (native selects), operable by keyboard alone; counts are text in the option labels.
 */
export function FilterBar({ domainId, state }: FilterBarProps): ReactElement {
  const styles = useStyles();
  const { filters, setFilter, clearAll, activeCount } = state;
  const counts = useFilterCounts({ domainId });
  const available = countsOf(counts.data);

  const [draft, setDraft] = useState(filters.tag);
  const [tagError, setTagError] = useState(false);
  // Back button, reload and "clear all" change the URL; the field follows it.
  useEffect(() => {
    setDraft(filters.tag);
    setTagError(false);
  }, [filters.tag]);

  function submitTag(event: FormEvent): void {
    event.preventDefault();
    const value = draft.trim();
    if (value !== "" && !isValidTag(value)) {
      setTagError(true); // rejected here; nothing reaches the URL or the server
      return;
    }
    setTagError(false);
    setFilter("tag", value);
  }

  return (
    <div
      className={styles.bar}
      role="group"
      aria-label={S.barLabel}
      data-testid="map-filter-bar"
      data-active-filters={activeCount}
    >
      {SELECTS.map(({ key, label, counts: countKey }) => {
        const served = available[countKey];
        // Only values the server accepts; the current value stays so the select never lies.
        const values = ALLOWED_VALUES[key].filter(
          (v) => (served[v] ?? 0) > 0 || v === filters[key],
        );
        const display = (v: string): string =>
          key === "node_type" ? kindLabel(v) : v.charAt(0).toUpperCase() + v.slice(1);
        return (
          <Field key={key} label={label}>
            <Select
              value={filters[key]}
              onChange={(_, data) => setFilter(key, data.value)}
              data-testid={`filter-${key}`}
            >
              <option value="">{S.all}</option>
              {values.map((v) => (
                <option key={v} value={v}>
                  {S.optionWithCount(display(v), served[v] ?? 0)}
                </option>
              ))}
            </Select>
          </Field>
        );
      })}

      <form className={styles.tagForm} onSubmit={submitTag} noValidate>
        <Field
          label={S.tag}
          hint={S.tagHint}
          validationState={tagError ? "error" : "none"}
          validationMessage={tagError ? S.tagInvalid : undefined}
        >
          <Input
            value={draft}
            onChange={(_, data) => {
              setDraft(data.value);
              setTagError(false);
            }}
            data-testid="filter-tag"
          />
        </Field>
        <Button type="submit" size="small" data-testid="filter-tag-apply">
          {S.applyTag}
        </Button>
      </form>

      {activeCount > 0 ? (
        <Button appearance="secondary" size="small" onClick={clearAll} data-testid="filter-clear">
          {S.clearAll(activeCount)}
        </Button>
      ) : null}
      {counts.isError ? (
        <span className={styles.muted} data-testid="filter-options-unavailable">
          {S.optionsUnavailable}
        </span>
      ) : null}
    </div>
  );
}
