import { Tree, TreeItem, TreeItemLayout, makeStyles, tokens } from "@fluentui/react-components";
import type { ReactElement } from "react";
import { StatusPill } from "../../design-system";
import { buildTree } from "./buildTree";
import { STRINGS, durationText, samplingText, spanLabel } from "./strings";
import type { Gap, Span, TraceNode } from "./types";

const useStyles = makeStyles({
  badges: {
    display: "inline-flex",
    flexWrap: "wrap",
    gap: tokens.spacingHorizontalXS,
    marginInlineStart: tokens.spacingHorizontalS,
    verticalAlign: "middle",
  },
});

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
  const styles = useStyles();
  // StatusPill wraps long text; a fixed-size Badge would clip the error and tool details.
  return (
    <span className={styles.badges} data-testid="span-badges">
      {span.status === "error" ? (
        <span data-testid="error-badge">
          <StatusPill
            label={`${STRINGS.error}${span.error !== null ? `: ${span.error}` : ""}`}
            tone="danger"
          />
        </span>
      ) : null}
      {span.kind === "tool" ? (
        <span data-testid="tool-badge">
          <StatusPill
            label={`${STRINGS.tool}: ${span.tool?.name ?? "unreported"} (${span.tool?.outcome ?? "unknown"})`}
            tone="neutral"
          />
        </span>
      ) : null}
      {span.late ? (
        <span data-testid="late-badge">
          <StatusPill
            label={`${STRINGS.late}${span.late_reason !== null ? `: ${span.late_reason}` : ""}`}
            tone="warning"
          />
        </span>
      ) : null}
      {span.sampled ? (
        <span data-testid="sampling-badge">
          <StatusPill label={samplingText(span.sampling_rate)} tone="neutral" />
        </span>
      ) : null}
      {gaps.map((g) => (
        <span key={g.reason} data-testid="gap-badge">
          <StatusPill label={STRINGS.gapReason[g.reason]} tone="danger" />
        </span>
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
