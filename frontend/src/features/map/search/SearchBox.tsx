import { Combobox, Option, makeStyles, tokens } from "@fluentui/react-components";
import { useState, type ComponentProps, type ReactElement } from "react";
import { useMapFilters } from "../filters/useMapFilters";
import { TRUNCATION_REASON_LABEL, kindLabel } from "../strings";
import type { SearchMatch } from "../types";
import { SEARCH_STRINGS as S } from "./strings";
import { useMapSearch } from "./useMapSearch";

const useStyles = makeStyles({
  root: { display: "grid", rowGap: tokens.spacingVerticalXXS, minWidth: "260px" },
  row: { display: "grid", rowGap: "2px" },
  meta: { color: tokens.colorNeutralForeground2, fontSize: tokens.fontSizeBase200 },
  status: { color: tokens.colorNeutralForeground2, fontSize: tokens.fontSizeBase200 },
});

export interface SearchBoxProps {
  readonly domainId: string;
  /** Called with the chosen match (the map jumps to it; the table focuses its row). */
  readonly onSelect: (match: SearchMatch) => void;
}

/** The three text facts shown for a result. A person's label is its pseudonym (server-side). */
export function matchText(match: SearchMatch): { label: string; meta: string } {
  const { node } = match;
  const environment = node.facets?.environment ?? S.unknownValue;
  const health = node.facets?.health ?? node.metrics.health;
  return {
    label: node.label,
    meta: `${kindLabel(node.kind)} · environment ${environment} · health ${health}`,
  };
}

/**
 * Accessible search combobox. Shared by the map and the table: it only reports the selection. The
 * active map filters (URL params) narrow the search. The result count is announced in a polite
 * live region, and every result states its kind, environment and health as text.
 */
export function SearchBox({ domainId, onSelect }: SearchBoxProps): ReactElement {
  const styles = useStyles();
  const filters = useMapFilters();
  const [text, setText] = useState("");
  const [open, setOpen] = useState(false);
  const search = useMapSearch(domainId, text, filters.toQuery());

  let announcement = "";
  if (search.error !== null) announcement = S.failed;
  else if (search.loading) announcement = S.searching;
  else if (search.active) {
    announcement = search.matches.length === 0 ? S.noMatches : S.count(search.matches.length);
  }
  const truncatedText =
    search.active && !search.loading && search.truncated
      ? S.truncated(
          search.truncationReason !== null
            ? TRUNCATION_REASON_LABEL[search.truncationReason]
            : S.truncatedFallback,
        )
      : "";

  // data-* attributes are not in the slot's declared type; they are forwarded to the <input>.
  const inputProps = { "data-testid": "map-search" } as unknown as ComponentProps<
    typeof Combobox
  >["input"];

  return (
    <div className={styles.root} data-testid="map-search-root">
      <Combobox
        aria-label={S.label}
        placeholder={S.placeholder}
        freeform
        value={text}
        selectedOptions={[]}
        open={open && search.active && search.matches.length > 0}
        onOpenChange={(_, data) => setOpen(data.open)}
        onChange={(event) => {
          setText(event.target.value);
          setOpen(true);
        }}
        onOptionSelect={(_, data) => {
          const match = search.matches.find((m) => m.node.id === data.optionValue);
          if (match === undefined) return;
          setText(match.node.label);
          setOpen(false);
          onSelect(match);
        }}
        input={inputProps}
      >
        {search.matches.map((match) => {
          const { label, meta } = matchText(match);
          return (
            <Option
              key={match.node.id}
              value={match.node.id}
              text={label}
              data-testid="map-search-result"
            >
              <span className={styles.row}>
                <span>{label}</span>
                <span className={styles.meta}>{meta}</span>
              </span>
            </Option>
          );
        })}
      </Combobox>
      <div
        role="status"
        aria-live="polite"
        className={styles.status}
        data-testid="map-search-status"
      >
        {announcement}
      </div>
      {truncatedText !== "" ? (
        <div className={styles.status} data-testid="map-search-truncated">
          {truncatedText}
        </div>
      ) : null}
    </div>
  );
}
