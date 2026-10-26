import {
  Table,
  TableBody,
  TableCell,
  TableHeader,
  TableHeaderCell,
  TableRow,
  makeStyles,
  mergeClasses,
  tokens,
} from "@fluentui/react-components";
import type { CSSProperties, ReactElement, ReactNode } from "react";
import { useUiStyle } from "../../design-system";

const useStyles = makeStyles({
  scroll: { overflowX: "auto", maxWidth: "100%" },
  strong: { borderTop: `${tokens.strokeWidthThin} solid ${tokens.colorNeutralStroke1}` },
  stripe: { ":nth-child(even)": { backgroundColor: tokens.colorNeutralBackground2 } },
  upper: { textTransform: "uppercase", letterSpacing: "0.06em", fontSize: tokens.fontSizeBase200 },
  cell: { overflowWrap: "anywhere" },
  tabular: { fontVariantNumeric: "tabular-nums" },
});

export interface RowTableColumn<T> {
  readonly key: string;
  readonly header: string;
  readonly render: (row: T) => ReactNode;
  readonly width?: string;
  readonly minWidth?: string;
}

export interface RowTableProps<T> {
  /** Accessible name of the table. */
  readonly label: string;
  readonly columns: readonly RowTableColumn<T>[];
  readonly rows: readonly T[];
  readonly getRowId: (row: T) => string;
  /** `data-testid` applied to every body row (specs and tests locate rows by it). */
  readonly rowTestId?: string;
  /** Extra `data-*` attributes per row, e.g. `{ "data-tool": name }`. */
  readonly rowAttrs?: (row: T) => Readonly<Record<string, string>>;
}

function widthStyle(c: RowTableColumn<unknown>): CSSProperties | undefined {
  if (c.width === undefined && c.minWidth === undefined) return undefined;
  return {
    ...(c.width === undefined ? {} : { width: c.width }),
    ...(c.minWidth === undefined ? {} : { minWidth: c.minWidth }),
  };
}

/**
 * Same look as the design-system `DataTable` (density, stripes, uppercase headers, tabular
 * numerals from the active style) with per-row `data-testid` / `data-*` hooks, which `DataTable`
 * does not offer. Switch to `DataTable` once it exposes row props.
 */
export function RowTable<T>({
  label,
  columns,
  rows,
  getRowId,
  rowTestId,
  rowAttrs,
}: RowTableProps<T>): ReactElement {
  const styles = useStyles();
  const { density, treatment } = useUiStyle();
  return (
    <div className={styles.scroll}>
      <Table
        aria-label={label}
        size={density === "compact" ? "small" : "medium"}
        className={treatment.border === "strong" ? styles.strong : undefined}
        data-slot="data-table"
      >
        <TableHeader>
          <TableRow>
            {columns.map((c) => (
              <TableHeaderCell
                key={c.key}
                className={mergeClasses(treatment.uppercaseLabels && styles.upper)}
                style={widthStyle(c as RowTableColumn<unknown>)}
              >
                {c.header}
              </TableHeaderCell>
            ))}
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.map((row) => (
            <TableRow
              key={getRowId(row)}
              className={treatment.tableStripes ? styles.stripe : undefined}
              data-testid={rowTestId}
              {...(rowAttrs === undefined ? {} : rowAttrs(row))}
            >
              {columns.map((c) => (
                <TableCell
                  key={c.key}
                  className={mergeClasses(
                    styles.cell,
                    treatment.numerals === "tabular" && styles.tabular,
                  )}
                  style={widthStyle(c as RowTableColumn<unknown>)}
                >
                  {c.render(row)}
                </TableCell>
              ))}
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}
