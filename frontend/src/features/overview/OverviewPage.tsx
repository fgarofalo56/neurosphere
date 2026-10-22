import { makeStyles, tokens } from "@fluentui/react-components";
import type { ReactElement, ReactNode } from "react";
import { Link } from "react-router";
import { ForbiddenError } from "../../api/index.js";
import { NO_DOMAINS_MESSAGE, useSelectedDomain } from "../../app/domain";
import { useRoles } from "../../auth/useRoles";
import { PageTemplate } from "../../design-system";
import { KindBadge, MetricText } from "../dashboards/components";
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
  type TileId,
} from "./data";
import { STRINGS } from "./strings";

const useStyles = makeStyles({
  grid: {
    display: "grid",
    gridTemplateColumns: "repeat(auto-fill, minmax(280px, 1fr))",
    gap: tokens.spacingHorizontalL,
    listStyleType: "none",
    margin: 0,
    padding: 0,
  },
  tile: {
    display: "flex",
    flexDirection: "column",
    rowGap: tokens.spacingVerticalS,
    padding: tokens.spacingHorizontalL,
    border: `1px solid ${tokens.colorNeutralStroke2}`,
    borderRadius: tokens.borderRadiusMedium,
    backgroundColor: tokens.colorNeutralBackground1,
  },
  heading: { margin: 0, fontSize: tokens.fontSizeBase400 },
  value: { fontSize: tokens.fontSizeHero700, fontWeight: tokens.fontWeightSemibold },
  rows: { margin: 0, padding: 0, listStyleType: "none" },
  muted: { color: tokens.colorNeutralForeground3 },
});

type QueryLike = { isPending: boolean; isError: boolean; error: unknown };

/** Own error state: a 403 is "no access", anything else "could not load"; the value is never 0. */
function problemText(q: QueryLike): string | null {
  if (!q.isError) return null;
  return q.error instanceof ForbiddenError ? STRINGS.forbidden : STRINGS.failed;
}

function Tile({
  id,
  title,
  domainId,
  linkLabel,
  children,
}: {
  readonly id: TileId;
  readonly title: string;
  readonly domainId: string;
  readonly linkLabel: string;
  readonly children: ReactNode;
}): ReactElement {
  const styles = useStyles();
  const headingId = `overview-tile-${id}`;
  return (
    <li>
      <section className={styles.tile} aria-labelledby={headingId} data-testid={`tile-${id}`}>
        <h2 id={headingId} className={styles.heading}>
          {title}
        </h2>
        {children}
        <Link to={tileHref(id, domainId)}>{linkLabel}</Link>
      </section>
    </li>
  );
}

/** Value line for a tile whose data is loading, failed or unknown. */
function Status({ q }: { readonly q: QueryLike }): ReactElement | null {
  const styles = useStyles();
  const problem = problemText(q);
  if (problem !== null) {
    return (
      <div role="alert">
        <div>{STRINGS.notLoaded}</div>
        <div className={styles.muted}>{problem}</div>
      </div>
    );
  }
  if (q.isPending) return <div role="status">{STRINGS.loading}</div>;
  return null;
}

function CostTile({ domainId }: { readonly domainId: string }): ReactElement {
  const styles = useStyles();
  const q = useCostTile({ domainId });
  // One row per series (kind and currency). Series are NEVER added together: estimated and
  // invoiced differ, and currencies must not be mixed.
  const rows = (q.data?.series ?? []).filter((s) => s.unit === "currency");
  return (
    <Tile id="cost" title={STRINGS.cost.title} domainId={domainId} linkLabel={STRINGS.cost.link}>
      <Status q={q} />
      {q.data !== undefined && rows.length === 0 ? (
        <div className={styles.value}>{STRINGS.unknown}</div>
      ) : null}
      {q.data !== undefined && rows.length > 0 ? (
        <ul className={styles.rows}>
          {rows.map((s) => (
            <li key={s.key} data-testid="cost-row">
              {s.currency !== null ? <strong>{s.currency}</strong> : null}{" "}
              {s.kind !== null ? <KindBadge kind={s.kind} /> : null}{" "}
              <MetricText metric={s.total} unit={s.currency ?? ""} />
            </li>
          ))}
        </ul>
      ) : null}
      <div className={styles.muted}>{STRINGS.cost.window}</div>
    </Tile>
  );
}

function ListTile({
  id,
  title,
  link,
  domainId,
  q,
  count,
}: {
  readonly id: TileId;
  readonly title: string;
  readonly link: string;
  readonly domainId: string;
  readonly q: QueryLike;
  readonly count: string | null;
}): ReactElement {
  const styles = useStyles();
  return (
    <Tile id={id} title={title} domainId={domainId} linkLabel={link}>
      <Status q={q} />
      {count !== null ? (
        <div className={styles.value} data-testid={`${id}-count`}>
          {count}
        </div>
      ) : null}
    </Tile>
  );
}

function ReviewTile({ domainId }: { readonly domainId: string }): ReactElement {
  const q = useReviewTile({ domainId });
  return (
    <ListTile
      id="review"
      title={STRINGS.review.title}
      link={STRINGS.review.link}
      domainId={domainId}
      q={q}
      count={q.data === undefined ? null : countText(q.data)}
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
  const q = useAwaitingTile({ domainId, state });
  const problem = problemText(q);
  const value =
    q.data !== undefined
      ? countText(q.data)
      : q.isPending
        ? STRINGS.loading
        : `${STRINGS.notLoaded} (${problem ?? STRINGS.failed})`;
  return (
    <li data-testid={`awaiting-${state}`}>
      {label}: <strong>{value}</strong>
    </li>
  );
}

function AwaitingTile({ domainId }: { readonly domainId: string }): ReactElement {
  const styles = useStyles();
  const labels: Record<AwaitingState, string> = {
    awaiting_confirmation: STRINGS.awaiting.confirmation,
    awaiting_approval: STRINGS.awaiting.approval,
  };
  return (
    <Tile
      id="awaiting"
      title={STRINGS.awaiting.title}
      domainId={domainId}
      linkLabel={STRINGS.awaiting.link}
    >
      {/* Two separate counts, never added: each is its own page and may carry "N+". */}
      <ul className={styles.rows}>
        {AWAITING_STATES.map((state) => (
          <AwaitingLine key={state} domainId={domainId} state={state} label={labels[state]} />
        ))}
      </ul>
    </Tile>
  );
}

function MapTile({ domainId }: { readonly domainId: string }): ReactElement {
  const styles = useStyles();
  const q = useMapTile({ domainId });
  const coverage = q.data?.coverage;
  return (
    <Tile id="map" title={STRINGS.map.title} domainId={domainId} linkLabel={STRINGS.map.link}>
      <Status q={q} />
      {coverage !== undefined ? (
        <>
          <div className={styles.value} data-testid="map-coverage">
            {coverage.state}
          </div>
          <div className={styles.muted}>
            {coverage.as_of !== null ? `${STRINGS.map.asOf} ${coverage.as_of}` : STRINGS.unknown}
          </div>
        </>
      ) : null}
    </Tile>
  );
}

function ReportsTile({ domainId }: { readonly domainId: string }): ReactElement {
  const styles = useStyles();
  const q = useReportsTile({ domainId });
  return (
    <Tile
      id="reports"
      title={STRINGS.reports.title}
      domainId={domainId}
      linkLabel={STRINGS.reports.link}
    >
      <Status q={q} />
      {q.data !== undefined ? (
        <>
          <div className={styles.value} data-testid="reports-count">
            {countText(q.data)}
          </div>
          <ul className={styles.rows}>
            {q.data.items.slice(0, 3).map((r) => (
              <li key={r.id}>{r.title}</li>
            ))}
          </ul>
        </>
      ) : null}
    </Tile>
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

/** Role-aware home page: summary tiles for the selected domain, each with its own state. */
export function OverviewPage(): ReactElement {
  const styles = useStyles();
  const { domainId, status } = useSelectedDomain();
  const { roles } = useRoles();
  const tiles = tilesForRoles(roles);

  let body: ReactNode;
  if (domainId === "") {
    body =
      status === "loading" ? (
        <p role="status">{STRINGS.loadingDomains}</p>
      ) : status === "forbidden" || status === "ready" ? (
        <p>{NO_DOMAINS_MESSAGE}</p>
      ) : (
        <p>{STRINGS.pickDomain}</p>
      );
  } else {
    body = (
      <ul className={styles.grid} aria-label={STRINGS.gridLabel}>
        {tiles.map((id) => (
          <TileFor key={id} id={id} domainId={domainId} />
        ))}
      </ul>
    );
  }

  return (
    <PageTemplate
      title={STRINGS.title}
      description={STRINGS.description}
      data-testid="overview-page"
    >
      {body}
    </PageTemplate>
  );
}
