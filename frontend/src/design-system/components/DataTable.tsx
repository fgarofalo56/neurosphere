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
import { useUiStyle } from "../styles";

const useStyles = makeStyles({
  strong: { borderTop: `${tokens.strokeWidthThin} solid ${tokens.colorNeutralStroke1}` },
  stripe: {
    ":nth-child(even)": { backgroundColor: tokens.colorNeutralBackground2 },
  },
  upper: { textTransform: "uppercase", letterSpacing: "0.06em", fontSize: tokens.fontSizeBase200 },
  cell: { overflowWrap: "anywhere" },
  tabular: { fontVariantNumeric: "tabular-nums" },
});

export interface DataTableColumn<T> {
  readonly key: string;
  readonly header: string;
  readonly render: (row: T) => ReactNode;
  /** Optional column width (any CSS length or percentage), e.g. "40%". */
  readonly width?: string;
  /** Optional minimum column width, e.g. "220px". */
  readonly minWidth?: string;
}

function widthStyle(c: {
  readonly width?: string;
  readonly minWidth?: string;
}): CSSProperties | undefined {
  if (c.width === undefined && c.minWidth === undefined) return undefined;
  return {
    ...(c.width === undefined ? {} : { width: c.width }),
    ...(c.minWidth === undefined ? {} : { minWidth: c.minWidth }),
  };
}

/** Extra attributes for a body row: `data-testid` and other `data-*` attributes only. */
export type DataTableRowProps = { readonly "data-testid"?: string } & {
  readonly [K in `data-${string}`]?: string | undefined;
};

/** Keeps only `data-*` keys, so an untyped caller cannot pass handlers or raw HTML. */
function dataAttributes(props: DataTableRowProps | undefined): Record<string, string> {
  const out: Record<string, string> = {};
  if (props === undefined) return out;
  for (const [key, value] of Object.entries(props)) {
    if (key.startsWith("data-") && typeof value === "string") out[key] = value;
  }
  return out;
}

export interface DataTableProps<T> {
  /** Accessible name of the table. */
  readonly label: string;
  readonly columns: readonly DataTableColumn<T>[];
  readonly rows: readonly T[];
  readonly getRowId: (row: T) => string;
  /** Optional `data-*` attributes (e.g. `data-testid`) applied to each body row. */
  readonly getRowProps?: (row: T) => DataTableRowProps;
}

/** Fluent `Table` sized by the active style's density, with optional stripes. */
export function DataTable<T>({
  label,
  columns,
  rows,
  getRowId,
  getRowProps,
}: DataTableProps<T>): ReactElement {
  const styles = useStyles();
  const { density, treatment } = useUiStyle();
  return (
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
              style={widthStyle(c)}
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
            {...dataAttributes(getRowProps?.(row))}
          >
            {columns.map((c) => (
              <TableCell
                key={c.key}
                className={mergeClasses(
                  styles.cell,
                  treatment.numerals === "tabular" && styles.tabular,
                )}
                style={widthStyle(c)}
              >
                {c.render(row)}
              </TableCell>
            ))}
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}
