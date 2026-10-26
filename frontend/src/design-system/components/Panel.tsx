import { makeStyles, mergeClasses, tokens } from "@fluentui/react-components";
import { useId, type ReactElement, type ReactNode } from "react";
import { useUiStyle } from "../styles";

const useStyles = makeStyles({
  panel: {
    display: "flex",
    flexDirection: "column",
    rowGap: tokens.spacingVerticalS,
    minWidth: 0,
    boxSizing: "border-box",
    padding: tokens.spacingHorizontalL,
    backgroundColor: tokens.colorNeutralBackground1,
    color: tokens.colorNeutralForeground1,
    border: `${tokens.strokeWidthThin} solid ${tokens.colorNeutralStroke2}`,
  },
  compact: { padding: tokens.spacingHorizontalM, rowGap: tokens.spacingVerticalXS },
  natural: { alignItems: "flex-start" },
  lifted: { backgroundColor: tokens.colorNeutralBackground2 },
  raised: { boxShadow: tokens.shadow4 },
  strong: { border: `${tokens.strokeWidthThin} solid ${tokens.colorNeutralStroke1}` },
  radiusSmall: { borderRadius: tokens.borderRadiusSmall },
  radiusMedium: { borderRadius: tokens.borderRadiusMedium },
  head: {
    display: "flex",
    flexWrap: "wrap",
    alignItems: "center",
    justifyContent: "space-between",
    columnGap: tokens.spacingHorizontalM,
    rowGap: tokens.spacingVerticalXXS,
  },
  title: {
    margin: 0,
    fontSize: tokens.fontSizeBase400,
    lineHeight: tokens.lineHeightBase400,
    fontWeight: tokens.fontWeightSemibold,
    overflowWrap: "anywhere",
  },
  upper: {
    textTransform: "uppercase",
    letterSpacing: "0.04em",
    fontSize: tokens.fontSizeBase200,
    color: tokens.colorNeutralForeground2,
  },
  note: { fontSize: tokens.fontSizeBase200, color: tokens.colorNeutralForeground2 },
});

export interface PanelProps {
  /** Section title, rendered as a heading of `level`. Omit for an untitled card. */
  readonly title?: string;
  /** Heading level of the title: 2 for a page section (default), 3 inside one. */
  readonly level?: 2 | 3;
  /** Accessible name for an untitled card; the card becomes a named `region`. */
  readonly label?: string;
  /**
   * Makes a titled card a named landmark whose name is its title: a `region`, or a `group`
   * (the role used by series blocks). Without it a titled card exposes no role.
   */
  readonly landmark?: "region" | "group";
  /** Small secondary text on the right of the title row, e.g. a unit. */
  readonly note?: ReactNode;
  /** Controls on the right of the title row, e.g. a Fluent Button. */
  readonly actions?: ReactNode;
  /** Tighter padding, and children keep their natural width (buttons, pills). */
  readonly compact?: boolean;
  /** Rendered as `data-testid` on the root element. */
  readonly testId?: string;
  readonly children?: ReactNode;
}

/**
 * Card section that follows the active UI style: surface, border, radius, label case and density
 * come from `useUiStyle()`, so both styles look native without per-feature copies.
 */
export function Panel({
  title,
  level = 2,
  label,
  landmark,
  note,
  actions,
  compact = false,
  testId,
  children,
}: PanelProps): ReactElement {
  const styles = useStyles();
  const headingId = useId();
  const { density, treatment } = useUiStyle();
  const Heading = level === 2 ? "h2" : "h3";
  const named: Record<string, string> = {};
  if (title !== undefined && landmark !== undefined) {
    named["aria-labelledby"] = headingId;
    if (landmark === "group") named["role"] = "group";
  } else if (label !== undefined) {
    named["aria-label"] = label;
  }
  const hasHead = title !== undefined || note !== undefined || actions !== undefined;
  return (
    <section
      className={mergeClasses(
        styles.panel,
        (compact || density === "compact") && styles.compact,
        compact && styles.natural,
        treatment.surface === "raised" && styles.raised,
        treatment.panelSurface === "lifted" && styles.lifted,
        treatment.border === "strong" && styles.strong,
        treatment.radius === "small" ? styles.radiusSmall : styles.radiusMedium,
      )}
      {...named}
      data-slot="panel"
      data-testid={testId}
    >
      {hasHead ? (
        <div className={styles.head}>
          {title === undefined ? null : (
            <Heading
              id={headingId}
              className={mergeClasses(styles.title, treatment.uppercaseLabels && styles.upper)}
            >
              {title}
            </Heading>
          )}
          {note === undefined ? null : <span className={styles.note}>{note}</span>}
          {actions}
        </div>
      ) : null}
      {children}
    </section>
  );
}
