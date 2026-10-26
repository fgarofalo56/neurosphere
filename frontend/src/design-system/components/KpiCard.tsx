import { makeStyles, mergeClasses, shorthands, tokens } from "@fluentui/react-components";
import { useId, type ReactElement, type ReactNode } from "react";
import { useUiStyle, type HealthState } from "../styles";
import { HealthIndicator } from "./status";

const useStyles = makeStyles({
  root: {
    display: "flex",
    flexDirection: "column",
    rowGap: tokens.spacingVerticalXS,
    minWidth: 0,
    boxSizing: "border-box",
    padding: tokens.spacingHorizontalM,
    backgroundColor: tokens.colorNeutralBackground1,
    color: tokens.colorNeutralForeground1,
    border: `${tokens.strokeWidthThin} solid ${tokens.colorNeutralStroke2}`,
  },
  compact: { padding: tokens.spacingHorizontalS, rowGap: tokens.spacingVerticalXXS },
  raised: { boxShadow: tokens.shadow4 },
  strong: { ...shorthands.borderColor(tokens.colorNeutralStroke1) },
  radiusSmall: { borderRadius: tokens.borderRadiusSmall },
  radiusMedium: { borderRadius: tokens.borderRadiusMedium },
  label: {
    fontSize: tokens.fontSizeBase200,
    lineHeight: tokens.lineHeightBase200,
    color: tokens.colorNeutralForeground2,
    overflowWrap: "anywhere",
  },
  upper: { textTransform: "uppercase", letterSpacing: "0.04em" },
  value: {
    fontSize: tokens.fontSizeHero700,
    lineHeight: tokens.lineHeightHero700,
    fontWeight: tokens.fontWeightSemibold,
    overflowWrap: "anywhere",
  },
  meta: {
    display: "flex",
    flexWrap: "wrap",
    alignItems: "center",
    columnGap: tokens.spacingHorizontalS,
    rowGap: tokens.spacingVerticalXXS,
    fontSize: tokens.fontSizeBase200,
  },
});

export interface KpiDelta {
  /** Already formatted, including the sign, e.g. "+4.2% vs last week". */
  readonly text: string;
  readonly direction: "up" | "down" | "flat";
}

export interface KpiCardProps {
  readonly label: string;
  /** Preformatted value; pass the format helpers' output ("unknown" for missing, never 0). */
  readonly value: ReactNode;
  readonly delta?: KpiDelta;
  readonly status?: HealthState;
  /** Optional sparkline slot (decorative or with its own text alternative). */
  readonly sparkline?: ReactNode;
}

const ARROWS = { up: "▲", down: "▼", flat: "▬" } as const;
const DIRECTION_WORDS = { up: "up", down: "down", flat: "unchanged" } as const;

/** Headline metric card. No heading elements; the group is named by its label. */
export function KpiCard({ label, value, delta, status, sparkline }: KpiCardProps): ReactElement {
  const styles = useStyles();
  const labelId = useId();
  const { density, treatment } = useUiStyle();
  return (
    <div
      role="group"
      aria-labelledby={labelId}
      className={mergeClasses(
        styles.root,
        density === "compact" && styles.compact,
        treatment.surface === "raised" && styles.raised,
        treatment.border === "strong" && styles.strong,
        treatment.radius === "small" ? styles.radiusSmall : styles.radiusMedium,
      )}
      data-slot="kpi-card"
    >
      <span
        id={labelId}
        className={mergeClasses(styles.label, treatment.uppercaseLabels && styles.upper)}
      >
        {label}
      </span>
      <span className={styles.value} data-slot="kpi-value">
        {value}
      </span>
      {delta === undefined && status === undefined ? null : (
        <span className={styles.meta}>
          {delta === undefined ? null : (
            <span data-slot="kpi-delta" data-direction={delta.direction}>
              <span aria-hidden="true">{ARROWS[delta.direction]} </span>
              {delta.text}
              <span style={visuallyHidden}>{` (${DIRECTION_WORDS[delta.direction]})`}</span>
            </span>
          )}
          {status === undefined ? null : <HealthIndicator state={status} />}
        </span>
      )}
      {sparkline === undefined ? null : <div data-slot="kpi-sparkline">{sparkline}</div>}
    </div>
  );
}

const visuallyHidden = {
  position: "absolute",
  width: 1,
  height: 1,
  overflow: "hidden",
  clipPath: "inset(50%)",
  whiteSpace: "nowrap",
} as const;
