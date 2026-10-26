import { Button, makeStyles, tokens } from "@fluentui/react-components";
import type { CSSProperties, ReactElement } from "react";
import {
  HealthIndicator,
  NODE_TYPES,
  PageTemplate,
  StatusPill,
  Timestamp,
  nodeTypeLabel,
  nodeTypeShape,
  useUiStyle,
  type NodeShape,
  type NodeType,
  type UiStyleId,
} from "../../../design-system";
import { MAP_EDGES, MAP_NODES, MOCKUP_NOW, type MapNode } from "./fixtures";
import { MockupFrame, Panel, type MockupMode } from "./MockupFrame";

const useStyles = makeStyles({
  layout: {
    display: "grid",
    gridTemplateColumns: "minmax(0, 1fr) 300px",
    columnGap: tokens.spacingHorizontalM,
    alignItems: "start",
  },
  side: { display: "flex", flexDirection: "column", rowGap: tokens.spacingVerticalM },
  svg: { display: "block", width: "100%", height: "auto" },
  legendRow: {
    display: "flex",
    alignItems: "center",
    columnGap: tokens.spacingHorizontalS,
    fontSize: tokens.fontSizeBase200,
    color: tokens.colorNeutralForeground1,
  },
  legendGroup: { display: "flex", flexDirection: "column", rowGap: tokens.spacingVerticalXS },
  defs: { display: "grid", gridTemplateColumns: "auto 1fr", columnGap: "12px", rowGap: "4px" },
  dt: { color: tokens.colorNeutralForeground2, fontSize: tokens.fontSizeBase200, margin: 0 },
  dd: { margin: 0, fontSize: tokens.fontSizeBase300, overflowWrap: "anywhere" },
  actions: { display: "flex", columnGap: tokens.spacingHorizontalS },
});

const SELECTED = "a1";

function shapePath(shape: NodeShape, r: number): string {
  switch (shape) {
    case "diamond":
      return `M0 ${-r - 2} L${r + 2} 0 L0 ${r + 2} L${-r - 2} 0 Z`;
    case "square":
      return `M${-r} ${-r} H${r} V${r} H${-r} Z`;
    case "hexagon": {
      const w = r * 0.87;
      return `M0 ${-r} L${w} ${-r / 2} L${w} ${r / 2} L0 ${r} L${-w} ${r / 2} L${-w} ${-r / 2} Z`;
    }
    case "pill":
      return `M${-r - 3} ${-r + 3} A${r - 3} ${r - 3} 0 0 1 ${-r + 3} ${-r} H${r - 3} A${r - 3} ${r - 3} 0 0 1 ${r + 3} ${-r + 3} V${r - 3} A${r - 3} ${r - 3} 0 0 1 ${r - 3} ${r} H${-r + 3} A${r - 3} ${r - 3} 0 0 1 ${-r - 3} ${r - 3} Z`;
    default:
      return `M${-r} 0 A${r} ${r} 0 1 0 ${r} 0 A${r} ${r} 0 1 0 ${-r} 0 Z`;
  }
}

function NodeGlyph({
  node,
  selected,
}: {
  readonly node: MapNode;
  readonly selected: boolean;
}): ReactElement {
  const { health } = useUiStyle();
  const colours = health[node.health];
  const halo: CSSProperties = { fill: colours.bg, stroke: colours.icon, strokeOpacity: 0.7 };
  const body: CSSProperties = {
    fill: tokens.colorNeutralBackground1,
    stroke: selected ? tokens.colorBrandStroke1 : tokens.colorNeutralForeground1,
  };
  const label: CSSProperties = { fill: tokens.colorNeutralForeground1 };
  return (
    <g transform={`translate(${node.x} ${node.y})`} data-node={node.id}>
      <circle r={25} style={halo} strokeWidth={1.5} />
      {selected ? (
        <circle r={31} fill="none" style={{ stroke: tokens.colorBrandStroke1 }} strokeWidth={2} />
      ) : null}
      <path d={shapePath(nodeTypeShape(node.type), 12)} style={body} strokeWidth={2} />
      <text
        y={42}
        textAnchor="middle"
        fontSize={12}
        fontWeight={selected ? 700 : 500}
        style={label}
      >
        {node.label}
      </text>
    </g>
  );
}

function MapSvg(): ReactElement {
  const styles = useStyles();
  const byId = new Map(MAP_NODES.map((n) => [n.id, n]));
  return (
    <svg
      className={styles.svg}
      viewBox="0 0 1000 600"
      role="img"
      aria-label={`Static mockup of the agent map: ${MAP_NODES.length} nodes with health halos and provenance edges`}
    >
      <g>
        {MAP_EDGES.map(([from, to], i) => {
          const a = byId.get(from);
          const b = byId.get(to);
          if (a === undefined || b === undefined) return null;
          const touchesSelected = from === SELECTED || to === SELECTED;
          const inferred = i % 4 === 3;
          const mx = (a.x + b.x) / 2;
          return (
            <path
              key={`${from}-${to}`}
              d={`M${a.x} ${a.y} C${mx} ${a.y} ${mx} ${b.y} ${b.x} ${b.y}`}
              fill="none"
              strokeWidth={touchesSelected ? 2.5 : 1.25}
              strokeDasharray={inferred ? "5 4" : undefined}
              style={{
                stroke: touchesSelected ? tokens.colorBrandStroke1 : tokens.colorNeutralStroke1,
              }}
            />
          );
        })}
      </g>
      {MAP_NODES.map((n) => (
        <NodeGlyph key={n.id} node={n} selected={n.id === SELECTED} />
      ))}
    </svg>
  );
}

function LegendShape({ type }: { readonly type: NodeType }): ReactElement {
  return (
    <svg width={22} height={22} viewBox="-13 -13 26 26" aria-hidden="true" focusable="false">
      <path
        d={shapePath(nodeTypeShape(type), 9)}
        strokeWidth={2}
        style={{
          fill: tokens.colorNeutralBackground1,
          stroke: tokens.colorNeutralForeground1,
        }}
      />
    </svg>
  );
}

export function MapMockup({
  styleId,
  mode,
}: {
  readonly styleId: UiStyleId;
  readonly mode: MockupMode;
}): ReactElement {
  const styles = useStyles();
  return (
    <MockupFrame styleId={styleId} mode={mode} active="Map">
      <PageTemplate
        title="Map"
        description="Agents, models and sources with curated and inferred provenance. Static mockup of the intended look."
        actions={<Button appearance="secondary">Open session replay</Button>}
      >
        <div className={styles.layout}>
          <Panel title="Agent map" note={`${MAP_NODES.length} nodes, ${MAP_EDGES.length} edges`}>
            <MapSvg />
          </Panel>
          <div className={styles.side}>
            <Panel title="Legend">
              <div className={styles.legendGroup}>
                {NODE_TYPES.map((t) => (
                  <span key={t} className={styles.legendRow}>
                    <LegendShape type={t} />
                    {nodeTypeLabel(t)}
                  </span>
                ))}
              </div>
              <div className={styles.legendGroup}>
                <HealthIndicator state="ok" />
                <HealthIndicator state="degraded" />
                <HealthIndicator state="failing" />
                <HealthIndicator state="unknown" />
              </div>
              <div className={styles.legendGroup}>
                <span className={styles.legendRow}>Solid edge: curated relationship</span>
                <span className={styles.legendRow}>Dashed edge: inferred from telemetry</span>
              </div>
            </Panel>
            <Panel title="support-triage">
              <div>
                <HealthIndicator state="degraded" label="Degraded: p95 latency" />
              </div>
              <dl className={styles.defs}>
                <dt className={styles.dt}>Type</dt>
                <dd className={styles.dd}>Agent</dd>
                <dt className={styles.dt}>Model</dt>
                <dd className={styles.dd}>gpt-4o (2 sub-agents)</dd>
                <dt className={styles.dt}>Owner</dt>
                <dd className={styles.dd}>Support leads</dd>
                <dt className={styles.dt}>Last seen</dt>
                <dd className={styles.dd}>
                  <Timestamp value="2026-10-24T11:42:00Z" now={MOCKUP_NOW} />
                </dd>
                <dt className={styles.dt}>Provenance</dt>
                <dd className={styles.dd}>
                  <StatusPill label="Curated, version 7" tone="success" />
                </dd>
              </dl>
              <div className={styles.actions}>
                <Button appearance="primary" size="small">
                  View recommendations
                </Button>
                <Button appearance="secondary" size="small">
                  Replay
                </Button>
              </div>
            </Panel>
          </div>
        </div>
      </PageTemplate>
    </MockupFrame>
  );
}
