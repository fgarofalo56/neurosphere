import { makeStyles, mergeClasses, shorthands, tokens } from "@fluentui/react-components";
import type { Theme } from "@fluentui/react-components";
import type { CSSProperties, ReactElement } from "react";
import { useUiStyle, type HealthState } from "../styles";

const usePillStyles = makeStyles({
  pill: {
    display: "inline-flex",
    alignItems: "center",
    maxWidth: "100%",
    boxSizing: "border-box",
    paddingBlock: tokens.spacingVerticalXXS,
    paddingInline: tokens.spacingHorizontalS,
    borderRadius: tokens.borderRadiusMedium,
    border: `${tokens.strokeWidthThin} solid transparent`,
    fontFamily: tokens.fontFamilyBase,
    fontSize: tokens.fontSizeBase200,
    lineHeight: tokens.lineHeightBase200,
    fontWeight: tokens.fontWeightSemibold,
    overflowWrap: "anywhere",
    whiteSpace: "normal",
    // No fixed height: long labels wrap instead of clipping.
  },
  neutral: {
    backgroundColor: tokens.colorNeutralBackground3,
    color: tokens.colorNeutralForeground1,
    ...shorthands.borderColor(tokens.colorNeutralStroke1),
  },
  info: {
    backgroundColor: tokens.colorBrandBackground2,
    // Neutral foreground: brand foreground on brand background 2 was too faint (axe color-contrast).
    color: tokens.colorNeutralForeground1,
    ...shorthands.borderColor(tokens.colorBrandStroke1),
  },
  success: {
    backgroundColor: tokens.colorStatusSuccessBackground1,
    color: tokens.colorStatusSuccessForeground1,
    ...shorthands.borderColor(tokens.colorStatusSuccessBorder1),
  },
  warning: {
    backgroundColor: tokens.colorStatusWarningBackground1,
    color: tokens.colorStatusWarningForeground1,
    ...shorthands.borderColor(tokens.colorStatusWarningBorder1),
  },
  danger: {
    backgroundColor: tokens.colorStatusDangerBackground1,
    color: tokens.colorStatusDangerForeground1,
    ...shorthands.borderColor(tokens.colorStatusDangerBorder1),
  },
});

export type StatusTone = "neutral" | "info" | "success" | "warning" | "danger";

/**
 * Theme-token (foreground, background) pair behind each pill tone. The pill styles above use
 * the same tokens; status.contrast.test.tsx checks every pair at 4.5:1 in every style, mode and pack.
 */
export const STATUS_TONE_TOKENS: Readonly<
  Record<StatusTone, readonly [fg: keyof Theme, bg: keyof Theme]>
> = {
  neutral: ["colorNeutralForeground1", "colorNeutralBackground3"],
  info: ["colorNeutralForeground1", "colorBrandBackground2"],
  success: ["colorStatusSuccessForeground1", "colorStatusSuccessBackground1"],
  warning: ["colorStatusWarningForeground1", "colorStatusWarningBackground1"],
  danger: ["colorStatusDangerForeground1", "colorStatusDangerBackground1"],
};

export interface StatusPillProps {
  /** Pill text; it is also the accessible name (no hidden or extra label). */
  readonly label: string;
  readonly tone?: StatusTone;
  /** Rendered as `data-testid` on the root element. */
  readonly testId?: string;
}

/** Wrapping status label. Meaning is carried by the text; tone is only reinforcement. */
export function StatusPill({ label, tone = "neutral", testId }: StatusPillProps): ReactElement {
  const styles = usePillStyles();
  // Never uppercased: pills carry words and sentences, and case is part of their meaning.
  return (
    <span
      className={mergeClasses(styles.pill, styles[tone])}
      data-slot="status-pill"
      data-tone={tone}
      data-testid={testId}
    >
      {label}
    </span>
  );
}

const useHealthStyles = makeStyles({
  root: {
    display: "inline-flex",
    alignItems: "center",
    columnGap: tokens.spacingHorizontalXS,
    paddingBlock: tokens.spacingVerticalXXS,
    paddingInline: tokens.spacingHorizontalS,
    borderRadius: tokens.borderRadiusMedium,
    fontFamily: tokens.fontFamilyBase,
    fontSize: tokens.fontSizeBase200,
    lineHeight: tokens.lineHeightBase200,
    fontWeight: tokens.fontWeightSemibold,
    overflowWrap: "anywhere",
  },
  icon: { flexShrink: 0 },
});

export const HEALTH_LABELS: Readonly<Record<HealthState, string>> = {
  ok: "Healthy",
  degraded: "Degraded",
  failing: "Failing",
  unknown: "Unknown",
};

function HealthGlyph({ state }: { readonly state: HealthState }): ReactElement {
  const common = {
    fill: "none",
    stroke: "currentColor",
    strokeWidth: 1.75,
    strokeLinecap: "round",
    strokeLinejoin: "round",
  } as const;
  // Distinct shapes per state so the glyph itself differs without colour.
  const body = {
    ok: (
      <>
        <circle cx="8" cy="8" r="6.5" {...common} />
        <path d="M5 8.2l2 2L11 6" {...common} />
      </>
    ),
    degraded: (
      <>
        <path d="M8 2l6.5 11.5h-13z" {...common} />
        <path d="M8 6.5v3M8 11.6v.1" {...common} />
      </>
    ),
    failing: (
      <>
        <circle cx="8" cy="8" r="6.5" {...common} />
        <path d="M5.5 5.5l5 5M10.5 5.5l-5 5" {...common} />
      </>
    ),
    unknown: (
      <>
        <circle cx="8" cy="8" r="6.5" {...common} strokeDasharray="2 2" />
        <path d="M6 6.3a2 2 0 013.9.6c0 1.3-1.9 1.6-1.9 2.8M8 11.8v.1" {...common} />
      </>
    ),
  } as const;
  return (
    <svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true" focusable="false">
      {body[state]}
    </svg>
  );
}

export interface HealthIndicatorProps {
  readonly state: HealthState;
  /** Replaces the default text ("Healthy", "Degraded", "Failing", "Unknown"). */
  readonly label?: string;
}

/** Health as colour plus icon plus text, taken from the active style's palette. Never colour alone. */
export function HealthIndicator({ state, label }: HealthIndicatorProps): ReactElement {
  const styles = useHealthStyles();
  const { health } = useUiStyle();
  const colours = health[state];
  const style: CSSProperties = { color: colours.fg, backgroundColor: colours.bg };
  const iconStyle: CSSProperties = { color: colours.icon };
  return (
    <span className={styles.root} style={style} data-slot="health-indicator" data-state={state}>
      <span className={styles.icon} style={iconStyle} data-slot="health-icon">
        <HealthGlyph state={state} />
      </span>
      <span>{label ?? HEALTH_LABELS[state]}</span>
    </span>
  );
}
