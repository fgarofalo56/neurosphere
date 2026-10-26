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
import type { ReactElement, ReactNode } from "react";
import { useUiStyle } from "../styles";

const useStyles = makeStyles({
  strong: { borderTop: `${tokens.strokeWidthThin} solid ${tokens.colorNeutralStroke1}` },
  stripe: {
    ":nth-child(even)": { backgroundColor: tokens.colorNeutralBackground2 },
  },
  upper: { textTransform: "uppercase", letterSpacing: "0.04em" },
  cell: { overflowWrap: "anywhere" },
});

export interface DataTableColumn<T> {
  readonly key: string;
  readonly header: string;
  readonly render: (row: T) => ReactNode;
}

export interface DataTableProps<T> {
  /** Accessible name of the table. */
  readonly label: string;
  readonly columns: readonly DataTableColumn<T>[];
  readonly rows: readonly T[];
  readonly getRowId: (row: T) => string;
}

/** Fluent `Table` sized by the active style's density, with optional stripes. */
export function DataTable<T>({ label, columns, rows, getRowId }: DataTableProps<T>): ReactElement {
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
          >
            {columns.map((c) => (
              <TableCell key={c.key} className={styles.cell}>
                {c.render(row)}
              </TableCell>
            ))}
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}
