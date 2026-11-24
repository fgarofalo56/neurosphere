import type { ReactElement, ReactNode } from "react";
import { NodeTypeIcon } from "../../design-system";
import type { NodeKind } from "./types";

const DESIGN_SYSTEM_KINDS: ReadonlySet<string> = new Set([
  "person",
  "agent",
  "sub_agent",
  "model",
  "source",
]);

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
  if (kind === "service") {
    return (
      <Svg>
        <path d="M12 3l8 6-3 11H7L4 9z" {...stroke} />
      </Svg>
    );
  }
  if (kind === "tool") {
    return (
      <Svg>
        <path d="M9 4h6v5h5v6h-5v5H9v-5H4V9h5z" {...stroke} />
      </Svg>
    );
  }
  if (kind === "mcp_server") {
    return (
      <Svg>
        <path d="M8.5 4h7L20 8.5v7L15.5 20h-7L4 15.5v-7z" {...stroke} />
      </Svg>
    );
  }
  if (!DESIGN_SYSTEM_KINDS.has(kind) && kind !== "cluster") {
    // A kind from a newer server: a generic glyph; the raw kind name is the text beside it.
    return (
      <Svg>
        <circle cx="12" cy="12" r="7" {...stroke} />
      </Svg>
    );
  }
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
