import { makeStyles, mergeClasses, tokens } from "@fluentui/react-components";
import type { ReactElement } from "react";
import { useUiStyle } from "../../design-system";
import { STRINGS } from "./strings";
import { useSandboxStore } from "./store";

const useStyles = makeStyles({
  banner: {
    display: "flex",
    flexWrap: "wrap",
    alignItems: "center",
    columnGap: tokens.spacingHorizontalM,
    rowGap: tokens.spacingVerticalXS,
    paddingBlock: tokens.spacingVerticalS,
    paddingInline: tokens.spacingHorizontalL,
    backgroundColor: tokens.colorStatusWarningBackground1,
    color: tokens.colorStatusWarningForeground1,
    borderBottom: `${tokens.strokeWidthThick} solid ${tokens.colorStatusWarningBorder1}`,
    fontWeight: tokens.fontWeightSemibold,
    // Forced-colors (Windows high contrast) drops backgrounds, so keep the border and system text.
    "@media (forced-colors: active)": {
      color: "CanvasText",
      borderBottom: `${tokens.strokeWidthThick} solid CanvasText`,
    },
  },
  glyph: { flexShrink: 0 },
  // Ops console: flat, square, dense, mono caption.
  ops: {
    paddingBlock: tokens.spacingVerticalXS,
    fontFamily: tokens.fontFamilyMonospace,
    fontSize: tokens.fontSizeBase200,
    borderTop: `${tokens.strokeWidthThin} solid ${tokens.colorStatusWarningBorder1}`,
  },
  // Enterprise Fluent: roomier, with a soft lift.
  enterprise: {
    paddingBlock: tokens.spacingVerticalM,
    boxShadow: tokens.shadow4,
  },
});

/** Visible only while sandbox mode is on; announced as a labelled region. */
export function SandboxBanner(): ReactElement | null {
  const enabled = useSandboxStore((s) => s.enabled);
  const styles = useStyles();
  const { id } = useUiStyle();
  if (!enabled) return null;
  return (
    <div
      role="region"
      aria-label={STRINGS.bannerName}
      className={mergeClasses(styles.banner, id === "ops-console" ? styles.ops : styles.enterprise)}
      data-testid="sandbox-banner"
    >
      <svg
        width="16"
        height="16"
        viewBox="0 0 16 16"
        aria-hidden="true"
        focusable="false"
        className={styles.glyph}
      >
        <path
          d="M8 2l6.5 11.5h-13z M8 6.5v3 M8 11.6v.1"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.75"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      </svg>
      {STRINGS.bannerText}
    </div>
  );
}
