import type { ReactElement, ReactNode } from "react";
import { NodeTypeIcon } from "../../design-system";
import type { Health, NodeKind } from "./types";

const stroke = {
  fill: "none",
  stroke: "currentColor",
  strokeWidth: 1.8,
  strokeLinecap: "round",
  strokeLinejoin: "round",
} as const;

function Svg({ children }: { readonly children: ReactNode }): ReactElement {
  return (
    <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true" focusable="false">
      {children}
    </svg>
  );
}

/** Distinct shapes per state: check in circle, triangle, octagon, question mark in circle. */
export function HealthIcon({ health }: { readonly health: Health }): ReactElement {
  switch (health) {
    case "ok":
      return (
        <Svg>
          <g data-shape="circle-check">
            <circle cx="12" cy="12" r="9" {...stroke} />
            <path d="M8 12.5l3 3 5-6" {...stroke} />
          </g>
        </Svg>
      );
    case "degraded":
      return (
        <Svg>
          <g data-shape="triangle">
            <path d="M12 3.5L21.5 20h-19z" {...stroke} />
            <path d="M12 10v4.5M12 17.2h.01" {...stroke} />
          </g>
        </Svg>
      );
    case "failing":
      return (
        <Svg>
          <g data-shape="octagon">
            <path d="M8.5 3h7L21 8.5v7L15.5 21h-7L3 15.5v-7z" {...stroke} />
            <path d="M9 9l6 6M15 9l-6 6" {...stroke} />
          </g>
        </Svg>
      );
    default:
      return (
        <Svg>
          <g data-shape="circle-question">
            <circle cx="12" cy="12" r="9" {...stroke} />
            <path d="M9.5 9.5a2.5 2.5 0 114 2c-.9.6-1.5 1.1-1.5 2.2M12 16.8h.01" {...stroke} />
          </g>
        </Svg>
      );
  }
}

/** Decorative: the kind is always also shown as text beside it. */
export function KindIcon({ kind }: { readonly kind: NodeKind }): ReactElement {
  if (kind === "cluster") {
    return (
      <Svg>
        <circle cx="8" cy="9" r="3" {...stroke} />
        <circle cx="16" cy="9" r="3" {...stroke} />
        <circle cx="12" cy="16" r="3" {...stroke} />
      </Svg>
    );
  }
  return (
    <span aria-hidden="true">
      <NodeTypeIcon type={kind === "sub_agent" ? "sub-agent" : kind} />
    </span>
  );
}
