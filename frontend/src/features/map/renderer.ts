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

function readLabelColour(container: HTMLElement): string {
  const colour = getComputedStyle(container).color;
  return colour !== "" ? colour : "#242424";
}

export function createMapRenderer(
  container: HTMLElement,
  graph: Graph<MapNodeAttributes, MapEdgeAttributes>,
  callbacks: RendererCallbacks,
): MapRenderer {
  const labelColor = readLabelColour(container);
  let selected: string | null = null;

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
        color: { attribute: "color", defaultValue: "#8a8886" },
        opacity: { attribute: "opacity", defaultValue: 1 },
        shape: { attribute: "shape", defaultValue: "circle" },
        label: { attribute: "label" },
        labelColor,
        visibility: { whenState: "isHidden", then: "hidden", else: "visible" },
        labelVisibility: {
          whenState: ["isHovered", "isHighlighted"],
          then: "visible",
          else: "auto",
        },
        backdropVisibility: {
          whenState: ["isHovered", "isHighlighted"],
          then: "visible",
          else: "hidden",
        },
        backdropColor: "#c7e0f4",
        backdropShadowColor: "rgba(15, 108, 189, 0.6)",
        backdropShadowBlur: 10,
        backdropPadding: 5,
      },
      edges: {
        size: { attribute: "size", defaultValue: 1 },
        color: { attribute: "color", defaultValue: "#a19f9d" },
        visibility: { whenState: "isHidden", then: "hidden", else: "visible" },
      },
    },
    settings: {
      renderEdgeLabels: false,
      enableEdgeEvents: false,
      labelRenderedSizeThreshold: 8,
      labelDensity: 0.35,
    },
  });

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
    setReducedMotion(reduced) {
      sigma.setSettings({
        inertiaDuration: reduced ? 0 : 3000,
        zoomDuration: reduced ? 0 : 250,
        doubleClickZoomingDuration: reduced ? 0 : 200,
      });
    },
    kill() {
      delete (container as HTMLElement & { __nsMap?: unknown }).__nsMap;
      sigma.kill();
    },
  };
}
