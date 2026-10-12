import { makeStyles, mergeClasses, tokens } from "@fluentui/react-components";
import type { ReactElement } from "react";

export type NodeType = "person" | "agent" | "sub-agent" | "model" | "source";

export const NODE_TYPES: readonly NodeType[] = ["person", "agent", "sub-agent", "model", "source"];

export type NodeShape = "circle" | "hexagon" | "diamond" | "square" | "pill";

interface NodeTypeSpec {
  readonly label: string;
  readonly shape: NodeShape;
  readonly glyph: ReactElement;
}

const stroke = {
  fill: "none",
  stroke: "currentColor",
  strokeWidth: 1.5,
  strokeLinecap: "round",
  strokeLinejoin: "round",
} as const;

/**
 * Original, neutral glyphs drawn inline (no vendor icon marks). Every glyph is
 * distinct, and each node type also has a distinct container shape and text label,
 * so type is never conveyed by color alone.
 */
const SPECS: Readonly<Record<NodeType, NodeTypeSpec>> = {
  person: {
    label: "Person",
    shape: "circle",
    glyph: (
      <>
        <circle cx="12" cy="8" r="3.5" {...stroke} />
        <path d="M5 20c0-3.9 3.1-6 7-6s7 2.1 7 6" {...stroke} />
      </>
    ),
  },
  agent: {
    label: "Agent",
    shape: "hexagon",
    glyph: (
      <>
        <rect x="5" y="8" width="14" height="11" rx="2.5" {...stroke} />
        <path d="M12 8V4.5M9.5 13h.01M14.5 13h.01" {...stroke} />
      </>
    ),
  },
  "sub-agent": {
    label: "Sub-agent",
    shape: "diamond",
    glyph: (
      <>
        <rect x="8" y="6" width="8" height="6" rx="1.5" {...stroke} />
        <path d="M12 12v3M7 18h10M7 18v-3M17 18v-3" {...stroke} />
      </>
    ),
  },
  model: {
    label: "Model",
    shape: "square",
    glyph: (
      <>
        <circle cx="6" cy="12" r="1.8" {...stroke} />
        <circle cx="18" cy="6" r="1.8" {...stroke} />
        <circle cx="18" cy="18" r="1.8" {...stroke} />
        <path d="M7.7 11.2l8.6-4.4M7.7 12.8l8.6 4.4" {...stroke} />
      </>
    ),
  },
  source: {
    label: "Source",
    shape: "pill",
    glyph: (
      <>
        <ellipse cx="12" cy="6.5" rx="6.5" ry="2.5" {...stroke} />
        <path d="M5.5 6.5v11c0 1.4 2.9 2.5 6.5 2.5s6.5-1.1 6.5-2.5v-11" {...stroke} />
        <path d="M5.5 12c0 1.4 2.9 2.5 6.5 2.5s6.5-1.1 6.5-2.5" {...stroke} />
      </>
    ),
  },
};

const useStyles = makeStyles({
  root: {
    display: "inline-flex",
    alignItems: "center",
    columnGap: tokens.spacingHorizontalS,
    color: tokens.colorNeutralForeground1,
  },
  badge: {
    width: "32px",
    height: "32px",
    display: "inline-flex",
    alignItems: "center",
    justifyContent: "center",
    backgroundColor: tokens.colorNeutralBackground3,
    color: tokens.colorNeutralForeground1,
    boxSizing: "border-box",
  },
  circle: { borderRadius: "50%" },
  hexagon: { clipPath: "polygon(25% 3%, 75% 3%, 100% 50%, 75% 97%, 25% 97%, 0% 50%)" },
  diamond: { clipPath: "polygon(50% 0%, 100% 50%, 50% 100%, 0% 50%)" },
  square: { borderRadius: tokens.borderRadiusNone },
  pill: { borderRadius: tokens.borderRadiusXLarge },
  svg: { width: "20px", height: "20px" },
});

export interface NodeTypeIconProps {
  type: NodeType;
  /** Show the text label beside the glyph. The accessible name is always present. */
  showLabel?: boolean;
}

export function nodeTypeLabel(type: NodeType): string {
  return SPECS[type].label;
}

export function nodeTypeShape(type: NodeType): NodeShape {
  return SPECS[type].shape;
}

export function NodeTypeIcon({ type, showLabel = false }: NodeTypeIconProps) {
  const styles = useStyles();
  const spec = SPECS[type];
  return (
    <span className={styles.root} data-node-type={type}>
      <span className={mergeClasses(styles.badge, styles[spec.shape])} data-shape={spec.shape}>
        <svg
          className={styles.svg}
          viewBox="0 0 24 24"
          role="img"
          aria-label={`${spec.label} node`}
          focusable="false"
        >
          {spec.glyph}
        </svg>
      </span>
      {showLabel ? <span aria-hidden="true">{spec.label}</span> : null}
    </span>
  );
}
