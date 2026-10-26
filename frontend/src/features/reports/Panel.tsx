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
});

/** Card-style region named by `label`, drawn from the active UI style's panel treatment. */
export function Panel({
  label,
  testId,
  children,
}: {
  readonly label: string;
  readonly testId?: string;
  readonly children: ReactNode;
}): ReactElement {
  const styles = useStyles();
  const { treatment } = useUiStyle();
  return (
    <section
      aria-label={label}
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
      {children}
    </section>
  );
}
