import { Badge, Tree, TreeItem, TreeItemLayout } from "@fluentui/react-components";
import type { ReactElement } from "react";
import { buildTree } from "./buildTree";
import { STRINGS, durationText, samplingText, spanLabel } from "./strings";
import type { Gap, Span, TraceNode } from "./types";

function allBranchIds(nodes: readonly TraceNode[], out: string[] = []): string[] {
  for (const n of nodes) {
    if (n.children.length > 0) {
      out.push(n.span.span_id);
      allBranchIds(n.children, out);
    }
  }
  return out;
}

function SpanBadges({
  span,
  gaps,
}: {
  readonly span: Span;
  readonly gaps: readonly Gap[];
}): ReactElement {
  return (
    <span data-testid="span-badges">
      {span.status === "error" ? (
        <Badge appearance="filled" color="danger" data-testid="error-badge">
          {STRINGS.error}
          {span.error !== null ? `: ${span.error}` : ""}
        </Badge>
      ) : null}
      {span.kind === "tool" ? (
        <Badge appearance="outline" color="informative" data-testid="tool-badge">
          {STRINGS.tool}: {span.tool?.name ?? "unreported"} ({span.tool?.outcome ?? "unknown"})
        </Badge>
      ) : null}
      {span.late ? (
        <Badge appearance="outline" color="warning" data-testid="late-badge">
          {STRINGS.late}
          {span.late_reason !== null ? `: ${span.late_reason}` : ""}
        </Badge>
      ) : null}
      {span.sampled ? (
        <Badge appearance="outline" color="warning" data-testid="sampling-badge">
          {samplingText(span.sampling_rate)}
        </Badge>
      ) : null}
      {gaps.map((g) => (
        <Badge key={g.reason} appearance="outline" color="danger" data-testid="gap-badge">
          {STRINGS.gapReason[g.reason]}
        </Badge>
      ))}
    </span>
  );
}

function Node({ node }: { readonly node: TraceNode }): ReactElement {
  const { span } = node;
  const layout = (
    <TreeItemLayout>
      <strong>{span.name}</strong> <span>({span.kind})</span>{" "}
      <span>{durationText(span.duration_ms)}</span> <SpanBadges span={span} gaps={node.gaps} />
    </TreeItemLayout>
  );
  if (node.children.length === 0) {
    return (
      <TreeItem itemType="leaf" value={span.span_id} aria-label={spanLabel(span)}>
        {layout}
      </TreeItem>
    );
  }
  return (
    <TreeItem itemType="branch" value={span.span_id} aria-label={spanLabel(span)}>
      {layout}
      <Tree>
        {node.children.map((c) => (
          <Node key={c.span.span_id} node={c} />
        ))}
      </Tree>
    </TreeItem>
  );
}

export interface TraceTreeProps {
  readonly spans: readonly Span[];
  readonly gaps: readonly Gap[];
}

/** Read-only, keyboard-navigable span tree (Fluent Tree: arrows, Home/End, Enter/space expand). */
export function TraceTree({ spans, gaps }: TraceTreeProps): ReactElement {
  const forest = buildTree(spans, gaps);
  return (
    <Tree aria-label={STRINGS.treeLabel} defaultOpenItems={allBranchIds(forest)}>
      {forest.map((n) => (
        <Node key={n.span.span_id} node={n} />
      ))}
    </Tree>
  );
}
