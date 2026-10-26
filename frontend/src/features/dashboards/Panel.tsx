import { makeStyles, mergeClasses, tokens } from "@fluentui/react-components";
import { useId, type ReactElement, type ReactNode } from "react";
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
    color: tokens.colorNeutralForeground1,
    border: `${tokens.strokeWidthThin} solid ${tokens.colorNeutralStroke2}`,
  },
  compact: { padding: tokens.spacingHorizontalM, rowGap: tokens.spacingVerticalXS },
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
  readonly title: string;
  /** Heading level of the title (h2 for a page section, h3 inside one). */
  readonly level?: 2 | 3;
  /** Right-aligned note, e.g. a health indicator or a unit. */
  readonly note?: ReactNode;
  /** Makes the panel a named `group` whose name is its title (used by series blocks). */
  readonly group?: boolean;
  readonly "data-testid"?: string;
  readonly children: ReactNode;
}

/** Card section that follows the active style (surface, border, radius, density). */
export function Panel({
  title,
  level = 3,
  note,
  group = false,
  "data-testid": testId,
  children,
}: PanelProps): ReactElement {
  const styles = useStyles();
  const headingId = useId();
  const { density, treatment } = useUiStyle();
  const Heading = level === 2 ? "h2" : "h3";
  return (
    <section
      className={mergeClasses(
        styles.panel,
        density === "compact" && styles.compact,
        treatment.surface === "raised" && styles.raised,
        treatment.panelSurface === "lifted" && styles.lifted,
        treatment.border === "strong" && styles.strong,
        treatment.radius === "small" ? styles.radiusSmall : styles.radiusMedium,
      )}
      {...(group ? { role: "group", "aria-labelledby": headingId } : {})}
      data-slot="panel"
      data-testid={testId}
    >
      <div className={styles.head}>
        <Heading
          id={headingId}
          className={mergeClasses(styles.title, treatment.uppercaseLabels && styles.upper)}
        >
          {title}
        </Heading>
        {note === undefined ? null : <span className={styles.note}>{note}</span>}
      </div>
      {children}
    </section>
  );
}
