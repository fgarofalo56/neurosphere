import { makeStyles, mergeClasses, tokens } from "@fluentui/react-components";
import type { ReactElement, ReactNode } from "react";
import { useUiStyle } from "../../design-system";

const useStyles = makeStyles({
  panel: {
    display: "flex",
    flexDirection: "column",
    rowGap: tokens.spacingVerticalS,
    minWidth: 0,
    boxSizing: "border-box",
    padding: tokens.spacingHorizontalL,
    backgroundColor: tokens.colorNeutralBackground1,
    border: `${tokens.strokeWidthThin} solid ${tokens.colorNeutralStroke2}`,
  },
  lifted: { backgroundColor: tokens.colorNeutralBackground2 },
  raised: { boxShadow: tokens.shadow4 },
  strong: { borderTopColor: tokens.colorNeutralStroke1 },
  radiusSmall: { borderRadius: tokens.borderRadiusSmall },
  radiusMedium: { borderRadius: tokens.borderRadiusMedium },
  heading: {
    margin: 0,
    fontSize: tokens.fontSizeBase400,
    lineHeight: tokens.lineHeightBase400,
    fontWeight: tokens.fontWeightSemibold,
  },
  upper: { textTransform: "uppercase", letterSpacing: "0.04em", fontSize: tokens.fontSizeBase300 },
});

/** Card-style section with an h2, drawn from the active UI style's panel treatment. */
export function Panel({
  id,
  title,
  testId,
  children,
}: {
  readonly id: string;
  readonly title: string;
  readonly testId?: string;
  readonly children: ReactNode;
}): ReactElement {
  const styles = useStyles();
  const { treatment } = useUiStyle();
  return (
    <section
      aria-labelledby={id}
      data-testid={testId}
      data-slot="panel"
      className={mergeClasses(
        styles.panel,
        treatment.panelSurface === "lifted" && styles.lifted,
        treatment.surface === "raised" && styles.raised,
        treatment.border === "strong" && styles.strong,
        treatment.radius === "small" ? styles.radiusSmall : styles.radiusMedium,
      )}
    >
      <h2
        id={id}
        className={mergeClasses(styles.heading, treatment.uppercaseLabels && styles.upper)}
      >
        {title}
      </h2>
      {children}
    </section>
  );
}

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
