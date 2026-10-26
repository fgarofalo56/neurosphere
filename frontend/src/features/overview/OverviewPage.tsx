import { makeStyles, tokens } from "@fluentui/react-components";
import type { ReactElement, ReactNode } from "react";
import { Link } from "react-router";
import { ForbiddenError } from "../../api/index.js";
import { NO_DOMAINS_MESSAGE, useSelectedDomain } from "../../app/domain";
import { useRoles } from "../../auth/useRoles";
import {
  EmptyState,
  ErrorState,
  KpiCard,
  LoadingState,
  PageTemplate,
  Sparkline,
  Timestamp,
  formatCurrency,
  formatNumber,
  useUiStyle,
  type HealthState,
} from "../../design-system";
import { MetricText } from "../dashboards/components";
import { Panel } from "../dashboards/Panel";
import type { Series } from "../dashboards/types";
import {
  AWAITING_STATES,
  countText,
  tileHref,
  tilesForRoles,
  useAwaitingTile,
  useCostTile,
  useMapTile,
  useReportsTile,
  useReviewTile,
  type AwaitingState,
  type MapCoverageResponse,
  type PagedList,
  type TileId,
} from "./data";
import { STRINGS } from "./strings";

const useStyles = makeStyles({
  tile: {
    display: "flex",
    flexDirection: "column",
    rowGap: tokens.spacingVerticalXS,
    minWidth: 0,
  },
  cards: { display: "flex", flexDirection: "column", rowGap: tokens.spacingVerticalS },
  lines: { display: "flex", flexDirection: "column", rowGap: tokens.spacingVerticalXXS },
  line: {
    fontSize: tokens.fontSizeBase400,
    lineHeight: tokens.lineHeightBase400,
    fontWeight: tokens.fontWeightRegular,
  },
  muted: { color: tokens.colorNeutralForeground2, fontSize: tokens.fontSizeBase200 },
  reports: {
    display: "flex",
    flexDirection: "column",
    rowGap: tokens.spacingVerticalXS,
    margin: 0,
    paddingInlineStart: tokens.spacingHorizontalL,
  },
});

type QueryLike = { isPending: boolean; isError: boolean; error: unknown };

/** Own error state: a 403 is "no access", anything else "could not load"; the value is never 0. */
function problemText(q: QueryLike): string | null {
  if (!q.isError) return null;
  return q.error instanceof ForbiddenError ? STRINGS.forbidden : STRINGS.failed;
}

function Tile({
  id,
  domainId,
  linkLabel,
  children,
}: {
  readonly id: TileId;
  readonly domainId: string;
  readonly linkLabel: string;
  readonly children: ReactNode;
}): ReactElement {
  const styles = useStyles();
  return (
    <div className={styles.tile} data-testid={`tile-${id}`}>
      {children}
      <Link to={tileHref(id, domainId)}>{linkLabel}</Link>
    </div>
  );
}

/** Loading or error panel standing in for a tile's card; the value is never shown as 0. */
function Problem({
  label,
  q,
}: {
  readonly label: string;
  readonly q: QueryLike;
}): ReactElement | null {
  const problem = problemText(q);
  if (problem !== null) {
    return <ErrorState title={`${label}: ${STRINGS.notLoaded}`} message={problem} />;
  }
  if (q.isPending) return <LoadingState label={`${STRINGS.loading} ${label}`} rows={2} />;
  return null;
}

function costAccent(s: Series): HealthState {
  if (s.total.status !== "known" || s.total.value === null) return "unknown";
  return s.total.complete ? "ok" : "degraded";
}

function costLabel(s: Series): string {
  const parts: string[] = [STRINGS.cost.label];
  if (s.currency !== null) parts.push(s.currency);
  if (s.kind !== null) parts.push(s.kind);
  return parts.join(", ");
}

function CostCard({ series }: { readonly series: Series }): ReactElement {
  const { density } = useUiStyle();
  const size = density === "compact" ? { width: 120, height: 22 } : { width: 180, height: 30 };
  const currency = series.currency;
  // Unknown points stay null so the sparkline breaks; they are never plotted as 0.
  const values = series.points.map((p) =>
    p.value.status === "known" && p.value.value !== null ? p.value.value : null,
  );
  return (
    <div data-testid="cost-row">
      <KpiCard
        label={costLabel(series)}
        value={
          <MetricText
            metric={series.total}
            format={(n) => (currency === null ? formatNumber(n) : formatCurrency(n, currency))}
          />
        }
        accent={costAccent(series)}
        sparkline={
          values.length > 0 ? (
            <Sparkline
              values={values}
              label={`${costLabel(series)}, daily`}
              kind={series.kind}
              unit="currency"
              currency={currency}
              {...size}
            />
          ) : undefined
        }
      />
    </div>
  );
}

function CostTile({ domainId }: { readonly domainId: string }): ReactElement {
  const styles = useStyles();
  const q = useCostTile({ domainId });
  // One card per series (kind and currency). Series are NEVER added together: estimated and
  // invoiced differ, and currencies must not be mixed.
  const rows = (q.data?.series ?? []).filter((s) => s.unit === "currency");
  return (
    <Tile id="cost" domainId={domainId} linkLabel={STRINGS.cost.link}>
      <Problem label={STRINGS.cost.label} q={q} />
      {q.data !== undefined && rows.length === 0 ? (
        <KpiCard label={STRINGS.cost.label} value={STRINGS.unknown} accent="unknown" />
      ) : null}
      {q.data !== undefined && rows.length > 0 ? (
        <div className={styles.cards}>
          {rows.map((s) => (
            <CostCard key={s.key} series={s} />
          ))}
        </div>
      ) : null}
      <div className={styles.muted}>{STRINGS.cost.window}</div>
    </Tile>
  );
}

function ListTile({
  id,
  label,
  link,
  domainId,
  q,
  list,
}: {
  readonly id: TileId;
  readonly label: string;
  readonly link: string;
  readonly domainId: string;
  readonly q: QueryLike;
  readonly list: PagedList<unknown> | undefined;
}): ReactElement {
  const more = list !== undefined && list.next_cursor !== null && list.next_cursor !== undefined;
  return (
    <Tile id={id} domainId={domainId} linkLabel={link}>
      <Problem label={label} q={q} />
      {list !== undefined ? (
        <KpiCard
          label={label}
          value={<span data-testid={`${id}-count`}>{countText(list)}</span>}
          {...(more ? { delta: { text: STRINGS.moreOnNextPage, direction: "flat" as const } } : {})}
        />
      ) : null}
    </Tile>
  );
}

function ReviewTile({ domainId }: { readonly domainId: string }): ReactElement {
  const q = useReviewTile({ domainId });
  return (
    <ListTile
      id="review"
      label={STRINGS.review.title}
      link={STRINGS.review.link}
      domainId={domainId}
      q={q}
      list={q.data}
    />
  );
}

function AwaitingLine({
  domainId,
  state,
  label,
}: {
  readonly domainId: string;
  readonly state: AwaitingState;
  readonly label: string;
}): ReactElement {
  const styles = useStyles();
  const q = useAwaitingTile({ domainId, state });
  const problem = problemText(q);
  const value =
    q.data !== undefined
      ? countText(q.data)
      : q.isPending
        ? STRINGS.loading
        : `${STRINGS.notLoaded} (${problem ?? STRINGS.failed})`;
  return (
    <span className={styles.line} data-testid={`awaiting-${state}`}>
      {label}: <strong>{value}</strong>
    </span>
  );
}

function AwaitingTile({ domainId }: { readonly domainId: string }): ReactElement {
  const styles = useStyles();
  const labels: Record<AwaitingState, string> = {
    awaiting_confirmation: STRINGS.awaiting.confirmation,
    awaiting_approval: STRINGS.awaiting.approval,
  };
  return (
    <Tile id="awaiting" domainId={domainId} linkLabel={STRINGS.awaiting.link}>
      {/* Two separate counts, never added: each is its own page and may carry "N+". */}
      <KpiCard
        label={STRINGS.awaiting.title}
        value={
          <span className={styles.lines}>
            {AWAITING_STATES.map((state) => (
              <AwaitingLine key={state} domainId={domainId} state={state} label={labels[state]} />
            ))}
          </span>
        }
      />
    </Tile>
  );
}

const COVERAGE_HEALTH: Record<MapCoverageResponse["coverage"]["state"], HealthState> = {
  complete: "ok",
  partial: "degraded",
  delayed: "degraded",
  unknown: "unknown",
};

function MapTile({ domainId }: { readonly domainId: string }): ReactElement {
  const styles = useStyles();
  const q = useMapTile({ domainId });
  const coverage = q.data?.coverage;
  return (
    <Tile id="map" domainId={domainId} linkLabel={STRINGS.map.link}>
      <Problem label={STRINGS.map.title} q={q} />
      {coverage !== undefined ? (
        <>
          <KpiCard
            label={STRINGS.map.title}
            value={<span data-testid="map-coverage">{coverage.state}</span>}
            status={COVERAGE_HEALTH[coverage.state]}
          />
          <div className={styles.muted}>
            {coverage.as_of !== null ? (
              <>
                {STRINGS.map.asOf} <Timestamp value={coverage.as_of} />
              </>
            ) : (
              STRINGS.unknown
            )}
          </div>
        </>
      ) : null}
    </Tile>
  );
}

function ReportsTile({ domainId }: { readonly domainId: string }): ReactElement {
  const q = useReportsTile({ domainId });
  return (
    <ListTile
      id="reports"
      label={STRINGS.reports.title}
      link={STRINGS.reports.link}
      domainId={domainId}
      q={q}
      list={q.data}
    />
  );
}

/** Recent report titles; shares the reports tile query (same key, so no extra call). */
function RecentReports({ domainId }: { readonly domainId: string }): ReactElement {
  const styles = useStyles();
  const q = useReportsTile({ domainId });
  return (
    <Panel title={STRINGS.reports.recent} level={2} data-testid="recent-reports">
      {q.isError || q.isPending ? <Problem label={STRINGS.reports.recent} q={q} /> : null}
      {q.data !== undefined && q.data.items.length === 0 ? (
        <EmptyState title={STRINGS.reports.emptyTitle} description={STRINGS.reports.emptyBody} />
      ) : null}
      {q.data !== undefined && q.data.items.length > 0 ? (
        <ul className={styles.reports}>
          {q.data.items.slice(0, 5).map((r) => (
            <li key={r.id}>{r.title}</li>
          ))}
        </ul>
      ) : null}
    </Panel>
  );
}

function TileFor({ id, domainId }: { readonly id: TileId; readonly domainId: string }) {
  switch (id) {
    case "cost":
      return <CostTile domainId={domainId} />;
    case "review":
      return <ReviewTile domainId={domainId} />;
    case "awaiting":
      return <AwaitingTile domainId={domainId} />;
    case "map":
      return <MapTile domainId={domainId} />;
    case "reports":
      return <ReportsTile domainId={domainId} />;
  }
}

/** Role-aware home page: summary KPI cards for the selected domain, each with its own state. */
export function OverviewPage(): ReactElement {
  const { domainId, status } = useSelectedDomain();
  const { roles } = useRoles();
  const tiles = tilesForRoles(roles);

  let body: ReactNode;
  if (domainId === "") {
    body =
      status === "loading" ? (
        <LoadingState label={STRINGS.loadingDomains} rows={2} />
      ) : status === "forbidden" || status === "ready" ? (
        <EmptyState title={NO_DOMAINS_MESSAGE} />
      ) : (
        <EmptyState title={STRINGS.pickDomain} />
      );
  } else {
    body = tiles.includes("reports") ? <RecentReports domainId={domainId} /> : null;
  }

  return (
    <PageTemplate
      title={STRINGS.title}
      description={STRINGS.description}
      data-testid="overview-page"
      {...(domainId === ""
        ? {}
        : {
            kpis: (
              <>
                {tiles.map((id) => (
                  <TileFor key={id} id={id} domainId={domainId} />
                ))}
              </>
            ),
          })}
    >
      {body}
    </PageTemplate>
  );
}
