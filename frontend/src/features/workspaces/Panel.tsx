import { makeStyles, mergeClasses, shorthands, tokens } from "@fluentui/react-components";
import type { ReactElement, ReactNode } from "react";
import { useUiStyle } from "../../design-system";

const useStyles = makeStyles({
  root: {
    display: "flex",
    flexDirection: "column",
    rowGap: tokens.spacingVerticalS,
    minWidth: 0,
    boxSizing: "border-box",
    padding: tokens.spacingHorizontalM,
    backgroundColor: tokens.colorNeutralBackground1,
    color: tokens.colorNeutralForeground1,
    border: `${tokens.strokeWidthThin} solid ${tokens.colorNeutralStroke2}`,
  },
  natural: { alignItems: "flex-start" },
  lifted: { backgroundColor: tokens.colorNeutralBackground2 },
  raised: { boxShadow: tokens.shadow4 },
  strong: { ...shorthands.borderColor(tokens.colorNeutralStroke1) },
  radiusSmall: { borderRadius: tokens.borderRadiusSmall },
  radiusMedium: { borderRadius: tokens.borderRadiusMedium },
  title: {
    margin: 0,
    fontSize: tokens.fontSizeBase300,
    lineHeight: tokens.lineHeightBase300,
    fontWeight: tokens.fontWeightSemibold,
    overflowWrap: "anywhere",
  },
  upper: {
    textTransform: "uppercase",
    letterSpacing: "0.04em",
    fontSize: tokens.fontSizeBase200,
    color: tokens.colorNeutralForeground2,
  },
});

export interface PanelProps {
  /** Section title, rendered as a level-2 heading. Omit for an untitled card. */
  readonly title?: string;
  readonly children: ReactNode;
  /** Keep children at their natural width (buttons, pills) instead of stretching them. */
  readonly compact?: boolean;
  readonly "data-testid"?: string;
}

/**
 * Card used by the workspace, action, review, MCP and sandbox pages. It follows the active UI
 * style's surface, border, radius and label treatment so both styles look native.
 */
export function Panel({
  title,
  children,
  compact = false,
  "data-testid": testId,
}: PanelProps): ReactElement {
  const styles = useStyles();
  const { treatment } = useUiStyle();
  return (
    <div
      className={mergeClasses(
        styles.root,
        compact && styles.natural,
        treatment.panelSurface === "lifted" && styles.lifted,
        treatment.surface === "raised" && styles.raised,
        treatment.border === "strong" && styles.strong,
        treatment.radius === "small" ? styles.radiusSmall : styles.radiusMedium,
      )}
      data-slot="panel"
      data-testid={testId}
    >
      {title === undefined ? null : (
        <h2 className={mergeClasses(styles.title, treatment.uppercaseLabels && styles.upper)}>
          {title}
        </h2>
      )}
      {children}
    </div>
  );
}
