import { makeStyles, tokens } from "@fluentui/react-components";
import type { ReactElement } from "react";
import { STRINGS } from "./strings";
import { useSandboxStore } from "./store";

const useStyles = makeStyles({
  banner: {
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
});

/** Visible only while sandbox mode is on; announced as a labelled region. */
export function SandboxBanner(): ReactElement | null {
  const enabled = useSandboxStore((s) => s.enabled);
  const styles = useStyles();
  if (!enabled) return null;
  return (
    <div
      role="region"
      aria-label={STRINGS.bannerName}
      className={styles.banner}
      data-testid="sandbox-banner"
    >
      {STRINGS.bannerText}
    </div>
  );
}
