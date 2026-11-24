import {
  Button,
  MessageBar,
  MessageBarBody,
  MessageBarTitle,
  Switch,
  makeStyles,
  mergeClasses,
  tokens,
} from "@fluentui/react-components";
import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type ReactElement,
} from "react";
import { Link } from "react-router";
import { ForbiddenError, useApiClient, type ApiError } from "../../api/index.js";
import { useSelectedDomain } from "../../app/domain";
import {
  ErrorState as StyledErrorState,
  LoadingState,
  PageTemplate,
  StatusPill,
  useUiStyle,
  type StatusTone,
} from "../../design-system";
import { NoDataEmptyState } from "../source-status";
import { ForbiddenState } from "../workspaces/ForbiddenState";
import { MAP_TABLE_PATH } from "../map-table/paths";
import { FilterBar } from "./filters/FilterBar";
import { useMapFilters } from "./filters/useMapFilters";
import { createBurstDebouncer, fetchViewport, useLiveUpdates, useViewport } from "./hooks";
import { Legend } from "./Legend";
import { MapCanvas } from "./MapCanvas";
import { MapGraph, worstCoverage } from "./mapGraph";
import { buildMapTheme, createDomResolver, type MapTheme } from "./mapTheme";
import { animationGate, useReducedMotion, type AnimationGate } from "./motion";
import { NodePanel, type ClusterExpansion } from "./NodePanel";
import type { Scheduler } from "./animator";
import { STRINGS, TRUNCATION_REASON_LABEL, coverageText } from "./strings";
import {
  NODE_BUDGET,
  type Coverage,
  type DeltaMessage,
  type SizeMetric,
  type TopologyMessage,
  type TruncationReason,
  type ViewportResponse,
} from "./types";
import type { LiveStatus } from "./realtime";

const useStyles = makeStyles({
  layout: {
    display: "flex",
    flexWrap: "wrap",
    gap: tokens.spacingHorizontalM,
    alignItems: "flex-start",
  },
  // minmax(0, 1fr): an implicit `auto` grid column sizes to its widest child's min-content and
  // overflows its container (it overlapped the legend at 1280px). The column must shrink instead.
  main: {
    flex: "1 1 520px",
    minWidth: 0,
    display: "grid",
    gridTemplateColumns: "minmax(0, 1fr)",
    rowGap: tokens.spacingVerticalS,
  },
  side: { display: "grid", rowGap: tokens.spacingVerticalM, flex: "0 0 auto" },
  toolbar: {
    display: "flex",
    flexWrap: "wrap",
    gap: tokens.spacingHorizontalM,
    alignItems: "center",
    paddingBlock: tokens.spacingVerticalXS,
    paddingInline: tokens.spacingHorizontalM,
    border: `1px solid ${tokens.colorNeutralStroke2}`,
    borderRadius: tokens.borderRadiusMedium,
    backgroundColor: tokens.colorNeutralBackground1,
  },
  toolbarLifted: { backgroundColor: tokens.colorNeutralBackground2 },
  link: {
    color: tokens.colorBrandForegroundLink,
    textDecorationLine: "none",
    fontWeight: tokens.fontWeightSemibold,
    ":hover": { textDecorationLine: "underline" },
  },
  muted: { color: tokens.colorNeutralForeground2, fontSize: tokens.fontSizeBase200 },
});

const LIVE_TONE: Readonly<Record<LiveStatus, StatusTone>> = {
  connecting: "info",
  live: "success",
  reconnecting: "warning",
  disconnected: "warning",
  unavailable: "warning",
  unauthenticated: "danger",
  revoked: "danger",
};

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
    <div data-testid="error-state">
      <StyledErrorState
        title={STRINGS.errorTitle}
        message={`${STRINGS.errorBody}${error.correlationId !== "" ? ` (reference ${error.correlationId})` : ""}`}
      />
    </div>
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
  const filterState = useMapFilters();
  const filterQuery = filterState.toQuery();
  const filterSignature = filterState.signature;
  const initial = useViewport({ domainId, filters: filterQuery });
  const uiStyle = useUiStyle();
  const layoutRef = useRef<HTMLDivElement | null>(null);
  const [theme, setTheme] = useState<MapTheme>(() => buildMapTheme(uiStyle, null));
  const [fitRequest, setFitRequest] = useState(0);
  const loaded = initial.isSuccess;

  // The canvas needs concrete colours: resolve the Fluent tokens against the live DOM (inside
  // the provider) whenever the style or colour mode changes. The key keeps the theme stable.
  useLayoutEffect(() => {
    const host = layoutRef.current;
    const next = buildMapTheme(uiStyle, host === null ? null : createDomResolver(host));
    setTheme((prev) => (prev.key === next.key ? prev : next));
  }, [uiStyle, loaded]);

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
  const appliedSignatureRef = useRef(filterSignature);
  // Every later page (refetch, load more, cluster expansion) carries the active filters.
  const filterQueryRef = useRef(filterQuery);
  filterQueryRef.current = filterQuery;
  useEffect(() => {
    const data = initial.data;
    if (data === undefined || initial.isPlaceholderData || appliedRef.current === data) return;
    appliedRef.current = data;
    if (appliedSignatureRef.current !== filterSignature) {
      // The filters changed: this page is a different slice of the domain. Drop the old slice so
      // counts and clusters reflect only matching nodes; camera and bar state are untouched.
      appliedSignatureRef.current = filterSignature;
      mapGraph.clear();
      setSources({});
      setExpansions({});
      setSelectedId(null);
    }
    applyPage("top:first", data);
    setTopCursor(data.next_cursor);
  }, [initial.data, initial.isPlaceholderData, filterSignature, mapGraph, applyPage]);

  const onDelta = useCallback(
    (delta: DeltaMessage) => {
      if (revokedRef.current) return; // a delta racing the 4403 close must not re-add nodes
      mapGraph.applyDelta(delta.nodes, delta.edges);
      setLiveCoverage(delta.coverage);
      bump();
    },
    [mapGraph, bump],
  );
  // A topology notice means nodes or edges came or went. Refetch the top level and every cluster
  // the user has opened, once per burst. Pages are merged (upsert), so camera, selection and the
  // positions of nodes already on screen are untouched; only new nodes get a slot.
  const expansionsRef = useRef(expansions);
  expansionsRef.current = expansions;
  const refetchBusyRef = useRef(false);
  const refetchQueuedRef = useRef(false);
  const refetchTopology = useCallback(async () => {
    if (revokedRef.current) return;
    if (refetchBusyRef.current) {
      refetchQueuedRef.current = true; // one more pass after the current one, never a pile-up
      return;
    }
    refetchBusyRef.current = true;
    try {
      const openClusters = Object.entries(expansionsRef.current)
        .filter(([, e]) => e.nextCursor !== undefined)
        .map(([id]) => id);
      const results = await Promise.allSettled([
        fetchViewport(client, {
          domainId,
          nodeBudget: NODE_BUDGET,
          filters: filterQueryRef.current,
        }),
        ...openClusters.map((clusterId) =>
          fetchViewport(client, {
            domainId,
            clusterId,
            nodeBudget: NODE_BUDGET,
            filters: filterQueryRef.current,
          }),
        ),
      ]);
      results.forEach((result, i) => {
        if (result.status !== "fulfilled") return; // keep the last good view; no blanking
        const clusterId = i === 0 ? null : openClusters[i - 1];
        applyPage(clusterId === null ? "top:first" : `cluster:${clusterId}:first`, result.value);
      });
    } finally {
      refetchBusyRef.current = false;
      if (refetchQueuedRef.current) {
        refetchQueuedRef.current = false;
        void refetchTopology();
      }
    }
  }, [client, domainId, applyPage]);
  const refetchTopologyRef = useRef(refetchTopology);
  refetchTopologyRef.current = refetchTopology;
  const topologyBurst = useMemo(
    () => createBurstDebouncer(() => void refetchTopologyRef.current()),
    [],
  );
  useEffect(() => () => topologyBurst.cancel(), [topologyBurst]);
  const onTopology = useCallback(
    (message: TopologyMessage) => {
      if (revokedRef.current || message.domain_id !== domainId) return;
      if (message.refetch || message.truncated) topologyBurst.trigger();
    },
    [domainId, topologyBurst],
  );

  const live = useLiveUpdates(domainId, initial.isSuccess, onDelta, onTopology);
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
    mapGraph.restyle({ sizeBy, animateEdges, theme });
    bump();
  }, [mapGraph, sizeBy, animateEdges, theme, bump]);

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
        filters: filterQueryRef.current,
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
          filters: filterQueryRef.current,
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

  // With filters active the bar must stay reachable (a rejected filter is cleared from it), so the
  // error is shown inline below; without filters it replaces the page as before.
  if (initial.isError && filterState.activeCount === 0) return <ErrorState error={initial.error} />;
  if (initial.isPending) {
    return (
      <div aria-busy="true" data-testid="map-loading">
        <LoadingState label={STRINGS.loading} rows={4} />
      </div>
    );
  }

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
    <div className={styles.layout} ref={layoutRef}>
      <div className={styles.main}>
        <div
          className={mergeClasses(
            styles.toolbar,
            uiStyle.treatment.panelSurface === "lifted" && styles.toolbarLifted,
          )}
        >
          <Link to={tableHref} className={styles.link} data-testid="view-as-table">
            {STRINGS.viewAsTable}
          </Link>
          <Switch
            label={motion.systemPrefers ? STRINGS.reduceMotionSystem : STRINGS.reduceMotion}
            checked={motion.reduced}
            disabled={motion.systemPrefers}
            onChange={(_, data) => motion.setAppToggle(data.checked)}
          />
          {/* After the switch: the pinned Tab order is "View as table", then the motion switch. */}
          <Button
            appearance="secondary"
            size="small"
            onClick={() => setFitRequest((n) => n + 1)}
            data-testid="fit-view"
          >
            {STRINGS.fitView}
          </Button>
          <span className={styles.muted} data-testid="animation-status">
            {ANIMATION_TEXT[animation]}
          </span>
          <span className={styles.muted} data-testid="node-count">
            {STRINGS.nodeCount(mapGraph.nodeCount, mapGraph.edgeCount)}
          </span>
          <FilterBar domainId={domainId} state={filterState} />
        </div>

        {initial.isError ? <ErrorState error={initial.error} /> : null}

        <div role="status" data-testid="live-status" data-live-status={live.status}>
          <StatusPill
            label={`${LIVE_TEXT[live.status]}${live.lastErrorCode !== null ? ` (${live.lastErrorCode})` : ""}`}
            tone={LIVE_TONE[live.status]}
          />
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

        {initial.data !== undefined &&
        initial.data.nodes.length === 0 &&
        mapGraph.nodeCount === 0 &&
        !revoked ? (
          <div data-testid="empty-state">
            <NoDataEmptyState what={STRINGS.empty} sources={["foundry", "apim_gateway"]} />
          </div>
        ) : null}

        <MapCanvas
          mapGraph={mapGraph}
          version={version}
          reducedMotion={motion.reduced}
          animateEdges={animateEdges}
          selectedId={selectedId}
          theme={theme}
          fitRequest={fitRequest}
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

export function MapPage(): ReactElement {
  const { domainId } = useSelectedDomain();
  return (
    <PageTemplate title={STRINGS.title} description={STRINGS.intro}>
      {domainId === "" ? (
        <p data-testid="domain-required">{STRINGS.domainRequired}</p>
      ) : (
        <MapView key={domainId} domainId={domainId} />
      )}
    </PageTemplate>
  );
}
