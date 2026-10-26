import type { ReactElement, ReactNode } from "react";
import { NodeTypeIcon } from "../../design-system";
import type { NodeKind } from "./types";

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
