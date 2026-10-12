import { makeStyles, tokens } from "@fluentui/react-components";
import type { ReactNode } from "react";

const useStyles = makeStyles({
  slot: {
    minWidth: "32px",
    minHeight: "32px",
    display: "inline-flex",
    alignItems: "center",
    justifyContent: "center",
    border: `${tokens.strokeWidthThin} dashed ${tokens.colorNeutralStroke1}`,
    borderRadius: tokens.borderRadiusMedium,
  },
});

export interface LogoSlotProps {
  /** Reserved for agency logos supplied by PRP-24 theme packs. Empty by default. */
  children?: ReactNode;
}

/** Neutral, empty logo region. Ships no brand mark. */
export function LogoSlot({ children }: LogoSlotProps) {
  const styles = useStyles();
  return (
    <div className={styles.slot} data-slot="logo">
      {children}
    </div>
  );
}
