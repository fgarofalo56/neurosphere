import { Button, makeStyles, tokens } from "@fluentui/react-components";
import type { ReactElement } from "react";
import { Link } from "react-router";
import { HealthIndicator, NodeTypeIcon } from "../../design-system";
import { useCardClasses } from "./card";
import { kindToNodeType } from "./appearance";
import { formatMetric } from "./Legend";
import type { MapNodeAttributes } from "./mapGraph";
import { HEALTH_LABEL, KIND_LABEL, SIZE_METRIC_LABEL, STRINGS } from "./strings";
import { SIZE_METRICS } from "./types";

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
        {isCluster ? (
          <strong>{KIND_LABEL.cluster}</strong>
        ) : (
          <NodeTypeIcon
            type={kindToNodeType(attrs.kind as Exclude<typeof attrs.kind, "cluster">)}
            showLabel
          />
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
        {SIZE_METRICS.map((m) => (
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
