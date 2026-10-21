import {
  Button,
  MessageBar,
  MessageBarBody,
  MessageBarTitle,
  Switch,
  makeStyles,
  tokens,
} from "@fluentui/react-components";
import { useCallback, useEffect, useMemo, useRef, useState, type ReactElement } from "react";
import { Link, useSearchParams } from "react-router";
import { ForbiddenError, useApiClient, type ApiError } from "../../api/index.js";
import { ForbiddenState } from "../workspaces/ForbiddenState";
import { MAP_TABLE_PATH } from "../map-table";
import { fetchViewport, useLiveUpdates, useViewport } from "./hooks";
import { Legend } from "./Legend";
import { MapCanvas } from "./MapCanvas";
import { MapGraph, worstCoverage } from "./mapGraph";
import { animationGate, useReducedMotion, type AnimationGate } from "./motion";
import { NodePanel, type ClusterExpansion } from "./NodePanel";
import type { Scheduler } from "./animator";
import { STRINGS, TRUNCATION_REASON_LABEL, coverageText } from "./strings";
import type {
  Coverage,
  DeltaMessage,
  SizeMetric,
  TruncationReason,
  ViewportResponse,
} from "./types";
import type { LiveStatus } from "./realtime";

const useStyles = makeStyles({
  layout: {
    display: "flex",
    flexWrap: "wrap",
    gap: tokens.spacingHorizontalM,
    alignItems: "flex-start",
  },
  main: { flex: "1 1 520px", minWidth: 0, display: "grid", rowGap: tokens.spacingVerticalS },
  side: { display: "grid", rowGap: tokens.spacingVerticalM, flex: "0 0 auto" },
  toolbar: {
    display: "flex",
    flexWrap: "wrap",
    gap: tokens.spacingHorizontalM,
    alignItems: "center",
  },
});

const LIVE_TEXT: Readonly<Record<LiveStatus, string>> = {
  connecting: STRINGS.liveConnecting,
  live: STRINGS.liveLive,
  reconnecting: STRINGS.liveReconnecting,
  disconnected: STRINGS.liveDisconnected,
  unavailable: STRINGS.liveUnavailable,
  unauthenticated: STRINGS.liveUnauthenticated,
  revoked: STRINGS.liveRevoked,
};

const ANIMATION_TEXT: Readonly<Record<AnimationGate, string>> = {
  on: STRINGS.edgeAnimationOn,
  reduced: STRINGS.edgeAnimationOffReduced,
  notLive: STRINGS.edgeAnimationOffNotLive,
  delayed: STRINGS.edgeAnimationOffDelayed,
  unknown: STRINGS.edgeAnimationOffUnknown,
};

function ErrorState({ error }: { readonly error: ApiError }): ReactElement {
  if (error instanceof ForbiddenError) {
    return <ForbiddenState workspace="Live map" correlationId={error.correlationId} />;
  }
  return (
    <MessageBar intent="error" role="alert" data-testid="error-state">
      <MessageBarBody>
        <MessageBarTitle>{STRINGS.errorTitle}</MessageBarTitle>
        {STRINGS.errorBody}
        {error.correlationId !== "" ? ` (reference ${error.correlationId})` : ""}
      </MessageBarBody>
    </MessageBar>
  );
}

interface PageSource {
  readonly coverage: Coverage;
  readonly truncated: boolean;
  readonly reason: TruncationReason | null;
}

export interface MapViewProps {
  readonly domainId: string;
  /** Test seam: deterministic frame scheduler for the edge animator. */
  readonly scheduler?: Scheduler;
}

/** Everything that depends on a loaded domain. Re-keyed per domain, so state never leaks across. */
export function MapView({ domainId, scheduler }: MapViewProps): ReactElement {
  const styles = useStyles();
  const client = useApiClient();
  const motion = useReducedMotion();
  const initial = useViewport({ domainId });

  const mapGraph = useMemo(() => new MapGraph(), []);
  const [version, setVersion] = useState(0);
  const bump = useCallback(() => setVersion((v) => v + 1), []);
  const [sizeBy, setSizeBy] = useState<SizeMetric>("tokens");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [sources, setSources] = useState<Readonly<Record<string, PageSource>>>({});
  const [expansions, setExpansions] = useState<Readonly<Record<string, ClusterExpansion>>>({});
  const [topCursor, setTopCursor] = useState<string | null>(null);
  const [topLoading, setTopLoading] = useState(false);
  const [topFailed, setTopFailed] = useState(false);
  const [liveCoverage, setLiveCoverage] = useState<Coverage | null>(null);

  const revokedRef = useRef(false);

  const applyPage = useCallback(
    (sourceKey: string, page: ViewportResponse) => {
      if (revokedRef.current) return; // an in-flight page must not redraw revoked data
      mapGraph.upsertNodes(page.nodes);
      mapGraph.upsertEdges(page.edges);
      mapGraph.restyle();
      setSources((prev) => ({
        ...prev,
        [sourceKey]: {
          coverage: page.coverage,
          truncated: page.truncated,
          reason: page.truncation_reason,
        },
      }));
      bump();
    },
    [mapGraph, bump],
  );

  // First page. Applied once per response object.
  const appliedRef = useRef<ViewportResponse | null>(null);
  useEffect(() => {
    const data = initial.data;
    if (data === undefined || appliedRef.current === data) return;
    appliedRef.current = data;
    applyPage("top:first", data);
    setTopCursor(data.next_cursor);
  }, [initial.data, applyPage]);

  const onDelta = useCallback(
    (delta: DeltaMessage) => {
      mapGraph.applyDelta(delta.nodes, delta.edges);
      setLiveCoverage(delta.coverage);
      bump();
    },
    [mapGraph, bump],
  );
  const live = useLiveUpdates(domainId, initial.isSuccess, onDelta);
  const revoked = live.status === "revoked";

  const coverage = useMemo(
    () =>
      worstCoverage([
        ...Object.values(sources).map((s) => s.coverage),
        ...(liveCoverage !== null ? [liveCoverage] : []),
      ]),
    [sources, liveCoverage],
  );

  // Observed edges animate only while the data is live and fresh enough: a map that animates
  // stale data as live is misleading. Reduced motion is checked first so its reason wins.
  const coverageState = coverage?.state ?? null;
  const animation = animationGate(motion.reduced, live.status, coverageState);
  const animateEdges = animation === "on";

  // Legend and animation gate drive the derived render attributes.
  useEffect(() => {
    if (revokedRef.current) return;
    mapGraph.restyle({ sizeBy, animateEdges });
    bump();
  }, [mapGraph, sizeBy, animateEdges, bump]);

  // Access revoked: remove the data from the view instead of leaving the last frame drawn.
  useEffect(() => {
    if (!revoked) return;
    revokedRef.current = true;
    mapGraph.clear();
    setSelectedId(null);
    bump();
  }, [revoked, mapGraph, bump]);

  useEffect(() => {
    const onKey = (event: KeyboardEvent): void => {
      if (event.key === "Escape") setSelectedId(null);
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, []);

  const loadTopMore = useCallback(async () => {
    if (revokedRef.current || topCursor === null || topLoading) return;
    if (mapGraph.remainingBudget <= 0) return;
    setTopLoading(true);
    setTopFailed(false);
    try {
      const page = await fetchViewport(client, {
        domainId,
        cursor: topCursor,
        nodeBudget: mapGraph.remainingBudget,
      });
      applyPage(`top:${topCursor}`, page);
      setTopCursor(page.next_cursor);
    } catch {
      setTopFailed(true);
    } finally {
      setTopLoading(false);
    }
  }, [client, domainId, topCursor, topLoading, mapGraph, applyPage]);

  const expandCluster = useCallback(
    async (clusterId: string) => {
      if (revokedRef.current) return;
      const current = expansions[clusterId];
      if (current?.loading === true) return;
      if (current?.nextCursor === null) return;
      if (mapGraph.remainingBudget <= 0) return;
      const cursor = current?.nextCursor ?? undefined;
      setExpansions((prev) => ({
        ...prev,
        [clusterId]: { loading: true, failed: false, nextCursor: current?.nextCursor },
      }));
      try {
        const page = await fetchViewport(client, {
          domainId,
          clusterId,
          ...(cursor !== undefined && { cursor }),
          nodeBudget: mapGraph.remainingBudget,
        });
        applyPage(`cluster:${clusterId}:${cursor ?? "first"}`, page);
        setExpansions((prev) => ({
          ...prev,
          [clusterId]: { loading: false, failed: false, nextCursor: page.next_cursor },
        }));
      } catch {
        setExpansions((prev) => ({
          ...prev,
          [clusterId]: { loading: false, failed: true, nextCursor: current?.nextCursor },
        }));
      }
    },
    [client, domainId, expansions, mapGraph, applyPage],
  );

  const onActivate = useCallback(
    (id: string) => {
      const attrs = mapGraph.graph.hasNode(id) ? mapGraph.graph.getNodeAttributes(id) : undefined;
      if (attrs?.kind === "cluster") void expandCluster(id);
    },
    [mapGraph, expandCluster],
  );

  if (initial.isError) return <ErrorState error={initial.error} />;
  if (initial.isPending) return <p aria-busy="true">{STRINGS.loading}</p>;

  const incomplete = Object.values(sources).filter((s) => s.truncated);
  const truncatedReason = incomplete[0]?.reason ?? null;
  const anyTruncated = incomplete.length > 0 || topCursor !== null;
  const selectedAttrs =
    selectedId !== null && mapGraph.graph.hasNode(selectedId)
      ? mapGraph.graph.getNodeAttributes(selectedId)
      : undefined;
  const budgetExhausted = mapGraph.remainingBudget <= 0;
  const tableHref = `${MAP_TABLE_PATH}?${new URLSearchParams({ domain_id: domainId }).toString()}`;

  return (
    <div className={styles.layout}>
      <div className={styles.main}>
        <div className={styles.toolbar}>
          <Link to={tableHref} data-testid="view-as-table">
            {STRINGS.viewAsTable}
          </Link>
          <Switch
            label={motion.systemPrefers ? STRINGS.reduceMotionSystem : STRINGS.reduceMotion}
            checked={motion.reduced}
            disabled={motion.systemPrefers}
            onChange={(_, data) => motion.setAppToggle(data.checked)}
          />
          <span data-testid="animation-status">{ANIMATION_TEXT[animation]}</span>
          <span data-testid="node-count">
            {STRINGS.nodeCount(mapGraph.nodeCount, mapGraph.edgeCount)}
          </span>
        </div>

        <div role="status" data-testid="live-status" data-live-status={live.status}>
          {LIVE_TEXT[live.status]}
          {live.lastErrorCode !== null ? ` (${live.lastErrorCode})` : ""}
        </div>

        {revoked ? (
          <MessageBar intent="error" role="alert" data-testid="access-revoked">
            <MessageBarBody>{STRINGS.accessRevoked}</MessageBarBody>
          </MessageBar>
        ) : null}

        {coverage !== null && !revoked ? (
          <MessageBar
            intent={coverage.state === "complete" ? "success" : "warning"}
            data-testid="coverage-label"
            data-coverage-state={coverage.state}
          >
            <MessageBarBody>
              {coverageText(coverage.state, coverage.lag_seconds, coverage.as_of)}
            </MessageBarBody>
          </MessageBar>
        ) : null}

        {anyTruncated && !revoked ? (
          <MessageBar intent="warning" data-testid="truncation-banner">
            <MessageBarBody>
              <MessageBarTitle>{STRINGS.truncatedTitle}</MessageBarTitle>
              {STRINGS.truncatedBody(
                truncatedReason !== null
                  ? TRUNCATION_REASON_LABEL[truncatedReason]
                  : "more data is available",
              )}
              {topCursor !== null ? (
                <>
                  {" "}
                  <Button
                    size="small"
                    disabled={topLoading || budgetExhausted}
                    onClick={() => void loadTopMore()}
                  >
                    {topLoading ? STRINGS.loadingMore : STRINGS.loadMore}
                  </Button>
                </>
              ) : null}
              {topFailed ? <span role="alert"> {STRINGS.loadMoreFailed}</span> : null}
              {budgetExhausted ? ` ${STRINGS.budgetReached}` : ""}
            </MessageBarBody>
          </MessageBar>
        ) : null}

        {initial.data.nodes.length === 0 && mapGraph.nodeCount === 0 && !revoked ? (
          <p data-testid="empty-state">{STRINGS.empty}</p>
        ) : null}

        <MapCanvas
          mapGraph={mapGraph}
          version={version}
          reducedMotion={motion.reduced}
          animateEdges={animateEdges}
          selectedId={selectedId}
          onSelect={setSelectedId}
          onActivate={onActivate}
          {...(scheduler !== undefined && { scheduler })}
        />
      </div>

      <div className={styles.side}>
        {selectedAttrs !== undefined && selectedId !== null ? (
          <NodePanel
            nodeId={selectedId}
            attrs={selectedAttrs}
            domainId={domainId}
            expansion={expansions[selectedId]}
            budgetExhausted={budgetExhausted}
            onExpand={(id) => void expandCluster(id)}
            onClose={() => setSelectedId(null)}
          />
        ) : null}
        <Legend
          sizeBy={sizeBy}
          onSizeBy={setSizeBy}
          range={mapGraph.sizeRange(sizeBy)}
          unknownCount={mapGraph.countUnknownSize()}
        />
      </div>
    </div>
  );
}

function DomainForm(): ReactElement {
  const [, setParams] = useSearchParams();
  const [value, setValue] = useState("");
  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        if (value.trim() !== "") setParams({ domain_id: value.trim() });
      }}
    >
      <label>
        {STRINGS.domainLabel} <input value={value} onChange={(e) => setValue(e.target.value)} />
      </label>{" "}
      <button type="submit">{STRINGS.domainSubmit}</button>
    </form>
  );
}

export function MapPage(): ReactElement {
  const [params] = useSearchParams();
  const domainId = params.get("domain_id") ?? "";
  return (
    <section aria-labelledby="map-heading">
      <h1 id="map-heading">{STRINGS.title}</h1>
      <p>{STRINGS.intro}</p>
      {domainId === "" ? (
        <>
          <p data-testid="domain-required">{STRINGS.domainRequired}</p>
          <DomainForm />
        </>
      ) : (
        <MapView key={domainId} domainId={domainId} />
      )}
    </section>
  );
}
