import {
  Table,
  TableBody,
  TableCell,
  TableHeader,
  TableHeaderCell,
  TableRow,
  makeStyles,
  tokens,
} from "@fluentui/react-components";
import type { ChartPlan } from "@neurosphere/contracts";
import { EmptyState, useUiStyle } from "../../design-system";
import { STRINGS } from "./strings";

export interface ChartTableProps {
  plan: ChartPlan;
  caption: string;
}

const useStyles = makeStyles({
  stripe: { ":nth-child(even)": { backgroundColor: tokens.colorNeutralBackground2 } },
  strong: { borderTop: `${tokens.strokeWidthThin} solid ${tokens.colorNeutralStroke1}` },
  upper: { textTransform: "uppercase", letterSpacing: "0.06em", fontSize: tokens.fontSizeBase200 },
  tabular: { fontVariantNumeric: "tabular-nums" },
  scroll: { overflowX: "auto", maxWidth: "100%" },
});

function cell(value: string | number | boolean | null | undefined): string {
  return value === null || value === undefined ? "" : String(value);
}

/** Plain accessible table of the plan's inline rows; always available beside the chart. */
export function ChartTable({ plan, caption }: ChartTableProps) {
  const styles = useStyles();
  const { density, treatment } = useUiStyle();
  const rows = plan.spec.data.values;
  const columns = [...new Set(rows.flatMap((row) => Object.keys(row)))];
  if (rows.length === 0) return <EmptyState title={STRINGS.noRows} />;
  return (
    <div className={styles.scroll}>
      <Table
        aria-label={caption}
        size={density === "compact" ? "extra-small" : "small"}
        className={treatment.border === "strong" ? styles.strong : undefined}
      >
        <TableHeader>
          <TableRow>
            {columns.map((column) => (
              <TableHeaderCell
                key={column}
                scope="col"
                className={treatment.uppercaseLabels ? styles.upper : undefined}
              >
                {column}
              </TableHeaderCell>
            ))}
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.map((row, i) => (
            <TableRow key={i} className={treatment.tableStripes ? styles.stripe : undefined}>
              {columns.map((column) => (
                <TableCell
                  key={column}
                  className={treatment.numerals === "tabular" ? styles.tabular : undefined}
                >
                  {cell(row[column])}
                </TableCell>
              ))}
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}
