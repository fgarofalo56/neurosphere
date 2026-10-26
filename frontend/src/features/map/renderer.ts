/**
 * The ONLY module that touches sigma. Unit tests mock this module (jsdom has no WebGL); the
 * rest of the feature talks to the small MapRenderer interface below.
 */
import Sigma from "sigma";
import {
  layerDashed,
  sdfCircle,
  sdfDiamond,
  sdfRectangle,
  sdfSquare,
  sdfTriangle,
  type SDFShape,
} from "sigma/rendering";
import type { MapEdgeAttributes, MapNodeAttributes } from "./mapGraph";
import { DEFAULT_MAP_THEME, type MapTheme } from "./mapTheme";
import type Graph from "graphology";

export interface RendererCallbacks {
  /** A node was clicked (id) or the empty stage was clicked (null). */
  onSelect(id: string | null): void;
  /** A node was double-clicked (used to expand clusters). */
  onActivate(id: string): void;
}

export interface MapRenderer {
  /** The graph's nodes, edges or attributes changed: re-index and redraw. */
  update(): void;
  /** Apply a new dash offset to the given edges and redraw only them. */
  setEdgeOffset(edgeIds: readonly string[], offset: number): void;
  select(id: string | null): void;
  /** Zoom-to-fit: reset the camera so the whole graph is in view. */
  fit(): void;
  /** Reduced motion: no camera inertia or animated zoom. */
  setReducedMotion(reduced: boolean): void;
  kill(): void;
}

/** Flat-top hexagon (agent). Follows sigma's SDF convention: positive outside. */
function sdfHexagon(): SDFShape {
  return {
    name: "hexagon",
    glsl: /*glsl*/ `
float sdf_hexagon(vec2 uv, float size) {
  const vec3 k = vec3(-0.866025404, 0.5, 0.577350269);
  float r = size * 0.866025404;
  vec2 p = abs(uv);
  p -= 2.0 * min(dot(k.xy, p), 0.0) * k.xy;
  p -= vec2(clamp(p.x, -k.z * r, k.z * r), r);
  return length(p) * sign(p.y);
}
`,
    uniforms: [],
    inradiusFactor: 0.866025404,
  };
}

const SOURCE_ASPECT_RATIO = 1.6;
/** Up to this many nodes every label is shown; beyond it sigma thins labels by density. */
const LABEL_ALL_NODES_MAX = 200;
/** Opacity of everything outside the hovered node's neighbourhood. */
const DIM_NODE_OPACITY = 0.35;
const DIM_EDGE_OPACITY = 0.12;

export function createMapRenderer(
  container: HTMLElement,
  graph: Graph<MapNodeAttributes, MapEdgeAttributes>,
  callbacks: RendererCallbacks,
  theme: MapTheme = DEFAULT_MAP_THEME,
): MapRenderer {
  let selected: string | null = null;
  let reduced = false;
  /** Neighbourhood highlighted by hover (nodes and edges), cleared on leave. */
  let hoverNodes: string[] = [];
  let hoverEdges: string[] = [];

  const labelStyle = (n: number): { threshold: number; density: number } =>
    n <= LABEL_ALL_NODES_MAX ? { threshold: 0, density: 3 } : { threshold: 8, density: 0.35 };
  const initialLabels = labelStyle(graph.order);
  let appliedLabels = initialLabels;

  const sigma = new Sigma(graph, container, {
    primitives: {
      nodes: {
        shapes: [
          sdfCircle(),
          sdfHexagon(),
          sdfDiamond(),
          sdfSquare(),
          sdfRectangle({ aspectRatio: SOURCE_ASPECT_RATIO }),
          sdfTriangle(),
        ],
      },
      edges: {
        layers: [
          layerDashed({
            dashSize: { attribute: "dashSize", default: 8, mode: "pixels" },
            gapSize: { attribute: "gapSize", default: 4, mode: "pixels" },
            dashOffset: { attribute: "dashOffset", default: 0, mode: "pixels" },
            dashColor: { attribute: "color" },
          }),
        ],
      },
    },
    styles: {
      nodes: {
        x: { attribute: "x" },
        y: { attribute: "y" },
        size: { attribute: "size", defaultValue: 4 },
        color: { attribute: "color", defaultValue: theme.health.unknown.icon },
        // Everything outside the hovered neighbourhood dims while a node is hovered.
        opacity: (attrs, state, graphState) => {
          const own = typeof attrs["opacity"] === "number" ? attrs["opacity"] : 1;
          return graphState.hasHovered && !state.isHovered && !state.isHighlighted
            ? own * DIM_NODE_OPACITY
            : own;
        },
        shape: { attribute: "shape", defaultValue: "circle" },
        label: { attribute: "label" },
        labelColor: theme.label.color,
        labelFont: theme.label.font,
        labelSize: theme.label.size,
        labelPosition: "below",
        labelBackgroundColor: theme.label.background,
        labelBackgroundPadding: 2,
        visibility: { whenState: "isHidden", then: "hidden", else: "visible" },
        labelVisibility: {
          whenState: ["isHovered", "isHighlighted"],
          then: "visible",
          else: "auto",
        },
        // The health halo: always on for small graphs (the halo attribute), emphasised on
        // hover and selection.
        backdropVisibility: {
          whenState: ["isHovered", "isHighlighted"],
          then: "visible",
          else: { attribute: "halo", defaultValue: "hidden" },
        },
        backdropColor: { attribute: "haloColor", defaultValue: theme.health.unknown.bg },
        backdropShadowColor: { attribute: "glowColor", defaultValue: "transparent" },
        backdropShadowBlur: theme.glow ? 14 : 0,
        backdropPadding: 6,
        backdropArea: "node",
        backdropBorderColor: theme.edge.observed,
        backdropBorderWidth: { whenState: ["isHovered", "isHighlighted"], then: 2, else: 0 },
      },
      edges: {
        size: { attribute: "size", defaultValue: 1 },
        color: { attribute: "color", defaultValue: theme.edge.inferred },
        opacity: (_attrs, state, graphState) =>
          graphState.hasHovered && !state.isHighlighted ? DIM_EDGE_OPACITY : 1,
        visibility: { whenState: "isHidden", then: "hidden", else: "visible" },
      },
    },
    settings: {
      renderEdgeLabels: false,
      enableEdgeEvents: false,
      stagePadding: 64,
      // Small graphs label every node; large ones keep sigma's density-based thinning.
      labelRenderedSizeThreshold: initialLabels.threshold,
      labelDensity: initialLabels.density,
    },
  });

  const clearHover = (): void => {
    for (const id of hoverNodes) {
      if (graph.hasNode(id) && id !== selected) sigma.setNodeState(id, { isHighlighted: false });
    }
    for (const id of hoverEdges) {
      if (graph.hasEdge(id)) sigma.setEdgeState(id, { isHighlighted: false });
    }
    hoverNodes = [];
    hoverEdges = [];
  };

  sigma.on("enterNode", ({ node }) => {
    clearHover();
    hoverNodes = graph.neighbors(node);
    hoverEdges = graph.edges(node);
    for (const id of hoverNodes) sigma.setNodeState(id, { isHighlighted: true });
    for (const id of hoverEdges) sigma.setEdgeState(id, { isHighlighted: true });
  });
  sigma.on("leaveNode", clearHover);
  sigma.on("clickNode", ({ node }) => callbacks.onSelect(node));
  sigma.on("clickStage", () => callbacks.onSelect(null));
  sigma.on("doubleClickNode", ({ node, preventSigmaDefault }) => {
    preventSigmaDefault();
    callbacks.onActivate(node);
  });

  if (!import.meta.env.PROD) {
    // Test hook (e2e and local debugging only; absent from production builds).
    (container as HTMLElement & { __nsMap?: unknown }).__nsMap = {
      camera: sigma.getCamera(),
      sigma,
      nodeCount: () => graph.order,
      edgeCount: () => graph.size,
    };
  }

  return {
    update() {
      const labels = labelStyle(graph.order);
      if (labels.density !== appliedLabels.density) {
        appliedLabels = labels;
        sigma.setSettings({
          labelRenderedSizeThreshold: labels.threshold,
          labelDensity: labels.density,
        });
      }
      sigma.refresh();
    },
    setEdgeOffset(edgeIds, offset) {
      for (const id of edgeIds) graph.setEdgeAttribute(id, "dashOffset", offset);
      sigma.scheduleRefresh({ partialGraph: { edges: [...edgeIds] }, skipIndexation: true });
    },
    select(id) {
      if (selected !== null && graph.hasNode(selected)) {
        sigma.setNodeState(selected, { isHighlighted: false });
      }
      selected = id;
      if (id !== null && graph.hasNode(id)) sigma.setNodeState(id, { isHighlighted: true });
    },
    fit() {
      void sigma.getCamera().reset({ duration: reduced ? 0 : 300 });
    },
    setReducedMotion(next) {
      reduced = next;
      sigma.setSettings({
        inertiaDuration: next ? 0 : 3000,
        zoomDuration: next ? 0 : 250,
        doubleClickZoomingDuration: next ? 0 : 200,
      });
    },
    kill() {
      delete (container as HTMLElement & { __nsMap?: unknown }).__nsMap;
      sigma.kill();
    },
  };
}
