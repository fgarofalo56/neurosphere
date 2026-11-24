import { useCallback, useEffect, useRef, useState } from "react";
import { useApiClient } from "../../../api/index.js";
import type { MapGraph } from "../mapGraph";
import { TRUNCATION_REASON_LABEL } from "../strings";
import type { NeighborhoodResponse, SearchMatch } from "../types";
import { SEARCH_STRINGS as S } from "./strings";

export function neighbourhoodPath(domainId: string, nodeId: string): string {
  // The route takes `{node_id:path}`: ids contain colons and slashes, so only the segments are
  // encoded and the slashes stay.
  const id = nodeId.split("/").map(encodeURIComponent).join("/");
  return `/api/v1/map/domains/${encodeURIComponent(domainId)}/neighborhood/${id}`;
}

export interface JumpOptions {
  readonly domainId: string;
  readonly mapGraph: MapGraph;
  /** The node currently selected: never dropped to make room. */
  readonly selectedId: string | null;
  /** The graph changed (merge): redraw. */
  readonly onGraphChanged: () => void;
  /** Select the node, open its panel and centre the camera (after the redraw). */
  readonly onJump: (nodeId: string) => void;
}

export interface JumpState {
  readonly jump: (match: SearchMatch) => void;
  /** Text to show after a jump (truncation, dropped nodes) or a failure; "" when none. */
  readonly note: string;
}

/**
 * Jump to a search result. A node already in the graph is just selected and centred; otherwise its
 * neighbourhood is fetched and merged under the node cap (the farthest unselected leaves of the
 * previous view make room) before it is selected and centred.
 */
export function useJumpToNode(options: JumpOptions): JumpState {
  const client = useApiClient();
  const [note, setNote] = useState("");
  const latest = useRef(options);
  latest.current = options;
  const controllerRef = useRef<AbortController | null>(null);
  useEffect(() => () => controllerRef.current?.abort(), []);

  const jump = useCallback(
    (match: SearchMatch) => {
      const { domainId, mapGraph, selectedId, onGraphChanged, onJump } = latest.current;
      const id = match.node.id;
      controllerRef.current?.abort();
      setNote("");
      if (mapGraph.graph.hasNode(id)) {
        onJump(id);
        return;
      }
      const controller = new AbortController();
      controllerRef.current = controller;
      client
        .get<NeighborhoodResponse>(neighbourhoodPath(domainId, id), undefined, controller.signal)
        .then((response) => {
          if (controller.signal.aborted) return;
          const keep = new Set<string>([id]);
          if (selectedId !== null) keep.add(selectedId);
          const merged = mapGraph.mergeNeighbourhood(id, response.nodes, response.edges, keep);
          const notes: string[] = [];
          if (response.truncated) {
            notes.push(
              S.jumpTruncated(
                response.truncation_reason !== null
                  ? TRUNCATION_REASON_LABEL[response.truncation_reason]
                  : "more neighbours exist",
              ),
            );
          }
          if (merged.dropped > 0) notes.push(S.jumpDropped(merged.dropped));
          if (merged.skipped > 0) notes.push(S.jumpSkipped(merged.skipped));
          if (!merged.centred) notes.push(S.jumpFailed);
          setNote(notes.join(" "));
          onGraphChanged();
          if (merged.centred) onJump(id);
        })
        .catch(() => {
          if (!controller.signal.aborted) setNote(S.jumpFailed);
        });
    },
    [client],
  );

  return { jump, note };
}
