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
