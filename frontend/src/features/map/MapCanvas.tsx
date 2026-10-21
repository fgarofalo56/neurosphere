import { makeStyles, tokens } from "@fluentui/react-components";
import { useEffect, useRef, useState, type ReactElement } from "react";
import { browserScheduler, createEdgeAnimator, type Scheduler } from "./animator";
import type { MapGraph } from "./mapGraph";
import { createMapRenderer, type MapRenderer } from "./renderer";
import { STRINGS } from "./strings";

const useStyles = makeStyles({
  frame: {
    position: "relative",
    width: "100%",
    height: "560px",
    border: `1px solid ${tokens.colorNeutralStroke1}`,
    borderRadius: tokens.borderRadiusMedium,
    backgroundColor: tokens.colorNeutralBackground1,
    color: tokens.colorNeutralForeground1,
    overflow: "hidden",
  },
  unavailable: { padding: tokens.spacingHorizontalL },
});

export interface MapCanvasProps {
  readonly mapGraph: MapGraph;
  /** Bumped whenever the graph changed; triggers a redraw. */
  readonly version: number;
  /** Reduced motion: also governs camera transitions and inertia. */
  readonly reducedMotion: boolean;
  /** Edge animation gate: motion allowed AND live AND coverage complete/partial. */
  readonly animateEdges: boolean;
  readonly selectedId: string | null;
  readonly onSelect: (id: string | null) => void;
  readonly onActivate: (id: string) => void;
  /** Test seam: deterministic frame scheduler. */
  readonly scheduler?: Scheduler;
}

/**
 * The WebGL view. It sits inside a region with an accessible name; the visible "View as table"
 * link on the page is the accessible equivalent. Testable signals live on the container:
 * data-edge-animation (on|off), data-animated-edges, data-animation-frames, data-node-count.
 */
export function MapCanvas({
  mapGraph,
  version,
  reducedMotion,
  animateEdges,
  selectedId,
  onSelect,
  onActivate,
  scheduler = browserScheduler,
}: MapCanvasProps): ReactElement {
  const styles = useStyles();
  const frameRef = useRef<HTMLDivElement | null>(null);
  const rendererRef = useRef<MapRenderer | null>(null);
  const animatorRef = useRef<ReturnType<typeof createEdgeAnimator> | null>(null);
  const callbacks = useRef({ onSelect, onActivate });
  callbacks.current = { onSelect, onActivate };
  const [failed, setFailed] = useState(false);
  const [ready, setReady] = useState(false);

  // Create the renderer once per graph; tear down on unmount.
  useEffect(() => {
    const frame = frameRef.current;
    if (frame === null) return;
    let renderer: MapRenderer;
    try {
      renderer = createMapRenderer(frame, mapGraph.graph, {
        onSelect: (id) => callbacks.current.onSelect(id),
        onActivate: (id) => callbacks.current.onActivate(id),
      });
    } catch {
      setFailed(true);
      return;
    }
    rendererRef.current = renderer;
    setReady(true);
    return () => {
      animatorRef.current?.stop();
      animatorRef.current = null;
      renderer.kill();
      rendererRef.current = null;
      setReady(false);
    };
  }, [mapGraph]);

  // Redraw when the graph changed.
  useEffect(() => {
    const frame = frameRef.current;
    rendererRef.current?.update();
    if (frame !== null) {
      frame.dataset["nodeCount"] = String(mapGraph.nodeCount);
      frame.dataset["edgeCount"] = String(mapGraph.edgeCount);
      frame.dataset["animatedEdges"] = String(mapGraph.animatedEdgeIds().length);
    }
  }, [mapGraph, version, ready]);

  useEffect(() => {
    rendererRef.current?.select(selectedId);
  }, [selectedId, ready]);

  useEffect(() => {
    rendererRef.current?.setReducedMotion(reducedMotion);
  }, [reducedMotion, ready]);

  // Edge animation: observed edges only, and only while the data is live and fresh enough.
  useEffect(() => {
    const frame = frameRef.current;
    const renderer = rendererRef.current;
    if (frame === null || renderer === null) return;
    frame.dataset["edgeAnimation"] = animateEdges ? "on" : "off";
    frame.dataset["animationFrames"] = "0";
    if (!animateEdges) {
      animatorRef.current?.stop();
      animatorRef.current = null;
      return;
    }
    const animator = createEdgeAnimator(
      {
        animatedEdgeIds: () => mapGraph.animatedEdgeIds(),
        setOffset: (ids, offset) => renderer.setEdgeOffset(ids, offset),
      },
      scheduler,
      (frames) => {
        frame.dataset["animationFrames"] = String(frames);
      },
    );
    animatorRef.current = animator;
    animator.start();
    return () => {
      animator.stop();
      if (animatorRef.current === animator) animatorRef.current = null;
    };
  }, [animateEdges, ready, mapGraph, scheduler]);

  return (
    <div
      ref={frameRef}
      className={styles.frame}
      role="region"
      aria-label={STRINGS.mapRegionName}
      data-testid="map-canvas"
      data-edge-animation={animateEdges ? "on" : "off"}
      data-renderer={failed ? "unavailable" : "webgl"}
    >
      {failed ? (
        <p className={styles.unavailable} role="alert">
          {STRINGS.webglUnavailable}
        </p>
      ) : null}
    </div>
  );
}
