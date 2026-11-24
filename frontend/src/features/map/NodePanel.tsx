import { Button, makeStyles, tokens } from "@fluentui/react-components";
import type { ReactElement } from "react";
import { Link } from "react-router";
import { HealthIndicator, NodeTypeIcon } from "../../design-system";
import { useCardClasses } from "./card";
import { isCoreKind as isCore, kindToNodeType } from "./appearance";
import { IMPACT_STRINGS } from "./impact/strings";
import { formatMetric } from "./Legend";
import type { MapNodeAttributes } from "./mapGraph";
import { HEALTH_LABEL, SIZE_METRIC_LABEL, STRINGS, kindLabel } from "./strings";
import { METRIC_KEYS, type MapNodeFacets } from "./types";

const useStyles = makeStyles({
  heading: { margin: 0, fontSize: tokens.fontSizeBase300, fontWeight: tokens.fontWeightSemibold },
  name: { margin: 0, fontSize: tokens.fontSizeBase400, fontWeight: tokens.fontWeightSemibold },
  muted: { margin: 0, color: tokens.colorNeutralForeground2, overflowWrap: "anywhere" },
  metrics: {
    display: "grid",
    gridTemplateColumns: "auto 1fr",
    columnGap: tokens.spacingHorizontalM,
    rowGap: tokens.spacingVerticalXXS,
    margin: 0,
  },
  term: { color: tokens.colorNeutralForeground2, fontSize: tokens.fontSizeBase200 },
  value: { margin: 0 },
  links: { listStyle: "none", margin: 0, padding: 0, display: "grid", rowGap: "4px" },
});

export interface ClusterExpansion {
  readonly loading: boolean;
  readonly failed: boolean;
  /** Undefined until the first page has been requested. */
  readonly nextCursor: string | null | undefined;
}

export interface NodePanelProps {
  readonly nodeId: string;
  readonly attrs: MapNodeAttributes;
  readonly domainId: string;
  readonly expansion: ClusterExpansion | undefined;
  readonly budgetExhausted: boolean;
  readonly onExpand: (clusterId: string) => void;
  readonly onClose: () => void;
  /** Start the incident view for this node; omitted where the view is not offered. */
  readonly onShowImpact?: () => void;
  /** The incident view already shows this node's dependents. */
  readonly impactShown?: boolean;
}

/** "Recent errors" as text: count, rate and last time; unknown is said, never shown as zero. */
function RecentErrors({ facets }: { readonly facets: MapNodeFacets | null }): ReactElement {
  const count = facets?.error_count ?? null;
  const rate = facets?.error_rate ?? null;
  const lastAt = facets?.last_error_at ?? null;
  const parts: string[] = [];
  if (count !== null) parts.push(STRINGS.errorCount(count));
  if (rate !== null) parts.push(STRINGS.errorRate(rate));
  if (lastAt !== null) parts.push(STRINGS.lastErrorAt(lastAt));
  const text = parts.length > 0 ? parts.join(", ") : STRINGS.recentErrorsUnknown;
  return (
    <p data-testid="panel-recent-errors">
      <strong>{STRINGS.recentErrors}:</strong> {text}
    </p>
  );
}

/** Environment, cloud, tags and health from the facets, as text. Hidden without facets. */
function FacetLines({ facets }: { readonly facets: MapNodeFacets | null }): ReactElement | null {
  const styles = useStyles();
  if (facets === null) return null;
  const tags = facets.tags ?? [];
  const health = facets.health;
  return (
    <dl className={styles.metrics} data-testid="panel-facets" aria-label={STRINGS.facetsHeading}>
      <dt className={styles.term}>{STRINGS.facetEnvironment}</dt>
      <dd className={styles.value} data-testid="facet-environment">
        {facets.environment ?? STRINGS.unknown}
      </dd>
      <dt className={styles.term}>{STRINGS.facetCloud}</dt>
      <dd className={styles.value} data-testid="facet-cloud">
        {facets.cloud ?? STRINGS.unknown}
      </dd>
      <dt className={styles.term}>{STRINGS.facetTags}</dt>
      <dd className={styles.value} data-testid="facet-tags">
        {tags.length > 0 ? tags.join(", ") : STRINGS.facetNone}
      </dd>
      {health !== undefined ? (
        <>
          <dt className={styles.term}>{STRINGS.facetHealth}</dt>
          <dd className={styles.value} data-testid="facet-health">
            {HEALTH_LABEL[health]}
          </dd>
        </>
      ) : null}
    </dl>
  );
}

function domainLink(path: string, domainId: string): string {
  return `${path}?${new URLSearchParams({ domain_id: domainId }).toString()}`;
}

/** Side panel for the selected node: metrics and links only. No actions beyond expanding. */
export function NodePanel({
  nodeId,
  attrs,
  domainId,
  expansion,
  budgetExhausted,
  onExpand,
  onClose,
  onShowImpact,
  impactShown = false,
}: NodePanelProps): ReactElement {
  const styles = useStyles();
  const card = useCardClasses();
  const isCluster = attrs.kind === "cluster";
  const started = expansion?.nextCursor !== undefined;
  const hasMore = expansion?.nextCursor !== undefined && expansion.nextCursor !== null;
  return (
    <aside className={card.card} aria-label={STRINGS.panelHeading} data-testid="node-panel">
      <h2 className={card.title}>{STRINGS.panelHeading}</h2>
      <div>
        {isCore(attrs.kind) ? (
          <NodeTypeIcon type={kindToNodeType(attrs.kind)} showLabel />
        ) : (
          <strong data-testid="panel-kind">{kindLabel(attrs.kind)}</strong>
        )}
      </div>
      <p className={styles.name} data-testid="panel-label">
        {attrs.label}
      </p>
      <p className={styles.muted}>
        <small>{nodeId}</small>
      </p>
      {isCluster ? (
        <p data-testid="panel-members">
          {attrs.memberCount === null ? STRINGS.unknown : STRINGS.members(attrs.memberCount)}
        </p>
      ) : null}
      <dl className={styles.metrics} data-testid="panel-metrics">
        {METRIC_KEYS.map((m) => (
          <div key={m} style={{ display: "contents" }}>
            <dt className={styles.term}>{SIZE_METRIC_LABEL[m]}</dt>
            <dd className={styles.value} data-testid={`metric-${m}`}>
              {formatMetric(attrs.metrics[m])}
            </dd>
          </div>
        ))}
        <dt className={styles.term}>Health</dt>
        <dd className={styles.value} data-testid="metric-health">
          <HealthIndicator
            state={attrs.metrics.health}
            label={HEALTH_LABEL[attrs.metrics.health]}
          />
        </dd>
      </dl>

      <RecentErrors facets={attrs.facets} />
      <FacetLines facets={attrs.facets} />

      {isCluster ? (
        <div>
          {!started || hasMore ? (
            <Button
              appearance="secondary"
              disabled={expansion?.loading === true || budgetExhausted}
              onClick={() => onExpand(nodeId)}
            >
              {expansion?.loading === true
                ? STRINGS.loadingMore
                : started
                  ? STRINGS.loadMore
                  : STRINGS.expandCluster}
            </Button>
          ) : null}
          {expansion?.failed === true ? <p role="alert">{STRINGS.loadMoreFailed}</p> : null}
          {budgetExhausted ? <p>{STRINGS.budgetReached}</p> : null}
        </div>
      ) : null}

      {!isCluster && onShowImpact !== undefined ? (
        <div>
          <Button
            appearance="primary"
            disabled={impactShown}
            onClick={onShowImpact}
            data-testid="show-impact"
          >
            {IMPACT_STRINGS.showImpact}
          </Button>
          <p className={styles.muted}>
            <small>{IMPACT_STRINGS.shortcut}</small>
          </p>
        </div>
      ) : null}

      <h3 className={styles.heading}>{STRINGS.linksHeading}</h3>
      <ul className={styles.links}>
        <li>
          <Link to={domainLink("/dashboards/cost", domainId)}>{STRINGS.linkCost}</Link>
        </li>
        <li>
          <Link to={domainLink("/dashboards/latency", domainId)}>{STRINGS.linkLatency}</Link>
        </li>
        <li>
          <Link to={domainLink("/recommendations", domainId)}>{STRINGS.linkRecommendations}</Link>
        </li>
        <li>
          <Link to={domainLink("/replay/traces", domainId)}>{STRINGS.linkReplay}</Link>
        </li>
      </ul>
      <Button appearance="subtle" onClick={onClose}>
        {STRINGS.panelClose}
      </Button>
    </aside>
  );
}
