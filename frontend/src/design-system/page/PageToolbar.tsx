import { makeStyles, tokens } from "@fluentui/react-components";
import type { ReactElement, ReactNode } from "react";

const useStyles = makeStyles({
  root: {
    display: "flex",
    flexWrap: "wrap",
    alignItems: "flex-end",
    columnGap: tokens.spacingHorizontalM,
    rowGap: tokens.spacingVerticalS,
    paddingBlock: tokens.spacingVerticalS,
  },
});

export interface PageToolbarProps {
  /** Filters and controls (Fluent `Field` + `Select`/`Input`, `Button`s), laid out in a wrapping row. */
  readonly children: ReactNode;
  /** Accessible name of the group. Defaults to "Filters". */
  readonly label?: string;
}

/**
 * Row of page filters and controls under the header. A labelled `group`, not an ARIA `toolbar`,
 * because it hosts form fields, which a toolbar's arrow-key model does not suit.
 */
export function PageToolbar({ children, label = "Filters" }: PageToolbarProps): ReactElement {
  const styles = useStyles();
  return (
    <div role="group" aria-label={label} className={styles.root} data-slot="page-toolbar">
      {children}
    </div>
  );
}
