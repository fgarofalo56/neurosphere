import type { Gap, Span, TraceNode } from "./types";

/**
 * Builds the span forest. Roots are spans with no parent or whose parent is absent (a gap).
 * Cycle-safe: a span is placed once; spans only reachable through a cycle become extra roots.
 */
export function buildTree(spans: readonly Span[], gaps: readonly Gap[]): TraceNode[] {
  const byId = new Map(spans.map((s) => [s.span_id, s]));
  const childIds = new Map<string, string[]>();
  const roots: string[] = [];
  for (const s of spans) {
    const parent = s.parent_span_id;
    if (parent !== null && byId.has(parent) && parent !== s.span_id) {
      const list = childIds.get(parent) ?? [];
      list.push(s.span_id);
      childIds.set(parent, list);
    } else {
      roots.push(s.span_id);
    }
  }
  const placed = new Set<string>();
  const gapsBySpan = new Map<string, Gap[]>();
  for (const g of gaps) {
    if (g.span_id !== null) gapsBySpan.set(g.span_id, [...(gapsBySpan.get(g.span_id) ?? []), g]);
  }

  const build = (id: string): TraceNode | undefined => {
    const span = byId.get(id);
    if (span === undefined || placed.has(id)) return undefined;
    placed.add(id);
    const children: TraceNode[] = [];
    for (const child of childIds.get(id) ?? []) {
      const node = build(child);
      if (node !== undefined) children.push(node);
    }
    return { span, children, gaps: gapsBySpan.get(id) ?? [] };
  };

  const out: TraceNode[] = [];
  for (const id of roots) {
    const node = build(id);
    if (node !== undefined) out.push(node);
  }
  for (const s of spans) {
    const node = build(s.span_id); // only reachable through a cycle
    if (node !== undefined) out.push(node);
  }
  return out;
}
