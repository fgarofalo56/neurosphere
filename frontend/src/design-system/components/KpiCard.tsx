import { makeStyles, mergeClasses, shorthands, tokens } from "@fluentui/react-components";
import { useId, type CSSProperties, type ReactElement, type ReactNode } from "react";
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
  lifted: { backgroundColor: tokens.colorNeutralBackground2 },
  edge: { position: "relative", paddingInlineStart: "14px" },
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
  valueCompact: { fontSize: tokens.fontSizeBase600, lineHeight: tokens.lineHeightBase600 },
  tabular: { fontVariantNumeric: "tabular-nums" },
  mono: { fontFamily: tokens.fontFamilyMonospace, letterSpacing: "-0.02em" },
  deltaGlyph: { display: "inline-block", verticalAlign: "-1px", marginInlineEnd: "4px" },
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
  /**
   * Colours the slim edge strip (Ops console style) without showing a health indicator. Falls
   * back to `status`; with neither, the strip is a neutral stroke colour.
   */
  readonly accent?: HealthState;
  /** Optional sparkline slot (decorative or with its own text alternative). */
  readonly sparkline?: ReactNode;
}

/** Direction glyphs as inline SVG; "flat" is a thin neutral dash, never a solid block. */
function DeltaGlyph({ direction }: { readonly direction: KpiDelta["direction"] }): ReactElement {
  const styles = useStyles();
  const shape =
    direction === "up" ? (
      <path d="M2 9l4-6 4 6z" fill="currentColor" />
    ) : direction === "down" ? (
      <path d="M2 3l4 6 4-6z" fill="currentColor" />
    ) : (
      <path d="M2 6h8" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
    );
  return (
    <svg
      className={styles.deltaGlyph}
      width="12"
      height="12"
      viewBox="0 0 12 12"
      aria-hidden="true"
      focusable="false"
      data-slot="kpi-delta-icon"
    >
      {shape}
    </svg>
  );
}

const DIRECTION_WORDS = { up: "up", down: "down", flat: "unchanged" } as const;

/** Headline metric card. No heading elements; the group is named by its label. */
export function KpiCard({
  label,
  value,
  delta,
  status,
  accent,
  sparkline,
}: KpiCardProps): ReactElement {
  const styles = useStyles();
  const labelId = useId();
  const { density, treatment, health } = useUiStyle();
  const edge = treatment.kpiAccent === "edge";
  const accentState = accent ?? status;
  const edgeStyle: CSSProperties | undefined = edge
    ? {
        boxShadow: `inset 3px 0 0 ${
          accentState === undefined ? tokens.colorNeutralStroke1 : health[accentState].icon
        }`,
      }
    : undefined;
  return (
    <div
      role="group"
      aria-labelledby={labelId}
      className={mergeClasses(
        styles.root,
        density === "compact" && styles.compact,
        treatment.surface === "raised" && styles.raised,
        treatment.panelSurface === "lifted" && styles.lifted,
        edge && styles.edge,
        treatment.border === "strong" && styles.strong,
        treatment.radius === "small" ? styles.radiusSmall : styles.radiusMedium,
      )}
      style={edgeStyle}
      data-slot="kpi-card"
      data-accent={edge ? (accentState ?? "none") : undefined}
    >
      <span
        id={labelId}
        className={mergeClasses(styles.label, treatment.uppercaseLabels && styles.upper)}
      >
        {label}
      </span>
      <span
        className={mergeClasses(
          styles.value,
          density === "compact" && styles.valueCompact,
          treatment.numerals === "tabular" && styles.tabular,
          treatment.monoNumerals && styles.mono,
        )}
        data-slot="kpi-value"
      >
        {value}
      </span>
      {delta === undefined && status === undefined ? null : (
        <span className={styles.meta}>
          {delta === undefined ? null : (
            <span data-slot="kpi-delta" data-direction={delta.direction}>
              <DeltaGlyph direction={delta.direction} />
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
