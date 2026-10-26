import { makeStyles, tokens } from "@fluentui/react-components";
import type { ReactElement } from "react";

const useStyles = makeStyles({
  wordmark: {
    display: "inline-flex",
    alignItems: "center",
    columnGap: tokens.spacingHorizontalS,
    color: tokens.colorNeutralForeground1,
  },
  text: {
    fontFamily: tokens.fontFamilyBase,
    fontSize: tokens.fontSizeBase500,
    fontWeight: tokens.fontWeightSemibold,
    lineHeight: tokens.lineHeightBase500,
  },
});

// Node positions on a 32x32 canvas: a sphere outline with linked nodes.
const NODES: readonly (readonly [number, number])[] = [
  [16, 6],
  [9, 12],
  [23, 12],
  [16, 16],
  [9, 21],
  [23, 21],
  [16, 26],
];
const LINKS: readonly (readonly [number, number])[] = [
  [0, 1],
  [0, 2],
  [1, 3],
  [2, 3],
  [1, 4],
  [2, 5],
  [3, 4],
  [3, 5],
  [4, 6],
  [5, 6],
];

export interface NeuroSphereMarkProps {
  /** Pixel size of the square mark. Defaults to 24. */
  readonly size?: number;
}

/**
 * Original NeuroSphere mark: a sphere of linked nodes. Decorative (`aria-hidden`); the wordmark
 * text carries the name. Inline JSX using `currentColor` only.
 */
export function NeuroSphereMark({ size = 24 }: NeuroSphereMarkProps): ReactElement {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 32 32"
      fill="none"
      aria-hidden="true"
      focusable="false"
      data-slot="neurosphere-mark"
    >
      <circle cx="16" cy="16" r="14" stroke="currentColor" strokeWidth="1.5" />
      {LINKS.map(([a, b]) => {
        const from = NODES[a];
        const to = NODES[b];
        if (from === undefined || to === undefined) return null;
        return (
          <line
            key={`${a}-${b}`}
            x1={from[0]}
            y1={from[1]}
            x2={to[0]}
            y2={to[1]}
            stroke="currentColor"
            strokeWidth="1"
            strokeLinecap="round"
          />
        );
      })}
      {NODES.map(([cx, cy]) => (
        <circle key={`${cx}-${cy}`} cx={cx} cy={cy} r="1.8" fill="currentColor" />
      ))}
    </svg>
  );
}

/** Mark plus the real text "NeuroSphere" (text is never inside the SVG). */
export function NeuroSphereWordmark({ size = 24 }: NeuroSphereMarkProps): ReactElement {
  const styles = useStyles();
  return (
    <span className={styles.wordmark} data-slot="neurosphere-wordmark">
      <NeuroSphereMark size={size} />
      <span className={styles.text}>NeuroSphere</span>
    </span>
  );
}
