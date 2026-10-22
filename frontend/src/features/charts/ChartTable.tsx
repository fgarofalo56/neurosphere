import {
  Table,
  TableBody,
  TableCell,
  TableHeader,
  TableHeaderCell,
  TableRow,
} from "@fluentui/react-components";
import type { ChartPlan } from "@neurosphere/contracts";
import { STRINGS } from "./strings";

export interface ChartTableProps {
  plan: ChartPlan;
  caption: string;
}

function cell(value: string | number | boolean | null | undefined): string {
  return value === null || value === undefined ? "" : String(value);
}

/** Plain accessible table of the plan's inline rows; always available beside the chart. */
export function ChartTable({ plan, caption }: ChartTableProps) {
  const rows = plan.spec.data.values;
  const columns = [...new Set(rows.flatMap((row) => Object.keys(row)))];
  if (rows.length === 0) return <p>{STRINGS.noRows}</p>;
  return (
    <Table aria-label={caption} size="small">
      <TableHeader>
        <TableRow>
          {columns.map((column) => (
            <TableHeaderCell key={column} scope="col">
              {column}
            </TableHeaderCell>
          ))}
        </TableRow>
      </TableHeader>
      <TableBody>
        {rows.map((row, i) => (
          <TableRow key={i}>
            {columns.map((column) => (
              <TableCell key={column}>{cell(row[column])}</TableCell>
            ))}
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}
