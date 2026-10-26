import { makeStyles, mergeClasses, tokens } from "@fluentui/react-components";
import { useUiStyle } from "../../design-system";

const useTableStyles = makeStyles({
  wrap: { overflowX: "auto", maxWidth: "100%" },
  table: {
    width: "100%",
    borderCollapse: "collapse",
    fontSize: tokens.fontSizeBase300,
  },
  caption: {
    textAlign: "start",
    fontWeight: tokens.fontWeightSemibold,
    paddingBlock: tokens.spacingVerticalXS,
  },
  cell: {
    textAlign: "start",
    verticalAlign: "top",
    paddingBlock: tokens.spacingVerticalXS,
    paddingInline: tokens.spacingHorizontalS,
    borderBottom: `${tokens.strokeWidthThin} solid ${tokens.colorNeutralStroke2}`,
    overflowWrap: "anywhere",
  },
  head: {
    color: tokens.colorNeutralForeground2,
    fontWeight: tokens.fontWeightSemibold,
    fontSize: tokens.fontSizeBase200,
  },
  upper: { textTransform: "uppercase", letterSpacing: "0.04em" },
  tabular: { fontVariantNumeric: "tabular-nums" },
});

/** Class names for the native tables whose row and cell test ids are part of the contract. */
export function useTableClasses(): {
  readonly wrap: string;
  readonly table: string;
  readonly caption: string;
  readonly th: string;
  readonly td: string;
} {
  const styles = useTableStyles();
  const { treatment } = useUiStyle();
  const num = treatment.numerals === "tabular" ? styles.tabular : undefined;
  return {
    wrap: styles.wrap,
    table: styles.table,
    caption: styles.caption,
    th: mergeClasses(styles.cell, styles.head, treatment.uppercaseLabels && styles.upper),
    td: mergeClasses(styles.cell, num),
  };
}
