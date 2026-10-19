import { MessageBar, MessageBarBody, MessageBarTitle } from "@fluentui/react-components";
import { useId, type ReactElement } from "react";
import { useSearchParams } from "react-router";
import { ForbiddenError } from "../../api/index.js";
import { ForbiddenState } from "../workspaces/ForbiddenState";
import { AnalyticsChip, LagIndicator, SeriesBlock } from "./components";
import { useDashboard } from "./hooks";
import { STRINGS } from "./strings";
import type { DashboardMetric, Grain } from "./types";

export interface DashboardPageProps {
  readonly title: string;
  readonly metrics: readonly DashboardMetric[];
}

const DAY_OPTIONS = [1, 7, 14, 30, 60, 90] as const;
const HOUR_MAX_DAYS = 14;

function MetricSection({
  metric,
  domainId,
  days,
  grain,
  title,
}: {
  readonly metric: DashboardMetric;
  readonly domainId: string;
  readonly days: number;
  readonly grain: Grain;
  readonly title: string;
}): ReactElement {
  const query = useDashboard({ metric, domainId, days, grain });

  if (query.isError) {
    const error = query.error;
    if (error instanceof ForbiddenError) {
      return <ForbiddenState workspace={title} correlationId={error.correlationId} />;
    }
    return (
      <MessageBar intent="error" role="alert" data-testid="error-state">
        <MessageBarBody>
          <MessageBarTitle>Could not load {metric}</MessageBarTitle>
          The request failed
          {error.correlationId !== "" ? ` (reference ${error.correlationId})` : ""}. This is not an
          empty result. Try again later.
        </MessageBarBody>
      </MessageBar>
    );
  }
  if (query.isPending) {
    return <p aria-busy="true">Loading {metric}...</p>;
  }
  const data = query.data;
  const showPrice = metric === "cost";
  return (
    <section aria-label={`${title} ${metric}`} data-testid={`section-${metric}`}>
      <h2>{metric}</h2>
      <div>
        <AnalyticsChip analytics={data.analytics} />
      </div>
      <LagIndicator freshness={data.freshness} />
      {!data.complete ? <p data-testid="incomplete-data">{STRINGS.incompleteData}</p> : null}
      {data.truncated ? <p data-testid="truncated">{STRINGS.truncated}</p> : null}
      {data.series.map((s) => (
        <SeriesBlock key={s.key} series={s} showPrice={showPrice} />
      ))}
    </section>
  );
}

export function DashboardPage({ title, metrics }: DashboardPageProps): ReactElement {
  const [params, setParams] = useSearchParams();
  const domainId = params.get("domain_id") ?? "";
  const rawDays = Number(params.get("days") ?? 30);
  const grain: Grain = params.get("grain") === "hour" ? "hour" : "day";
  const days = Number.isInteger(rawDays) && rawDays >= 1 && rawDays <= 90 ? rawDays : 30;
  const effectiveDays = grain === "hour" ? Math.min(days, HOUR_MAX_DAYS) : days;
  const ids = { domain: useId(), days: useId(), grain: useId() };

  const update = (key: string, value: string): void => {
    const next = new URLSearchParams(params);
    next.set(key, value);
    if (key === "grain" && value === "hour" && days > HOUR_MAX_DAYS) {
      next.set("days", String(HOUR_MAX_DAYS));
    }
    setParams(next);
  };

  return (
    <section aria-label={`${title} dashboard`}>
      <h1>{title}</h1>
      <form
        aria-label="Dashboard filters"
        onSubmit={(e) => {
          e.preventDefault();
          const value = new FormData(e.currentTarget).get("domain_id");
          update("domain_id", typeof value === "string" ? value.trim() : "");
        }}
      >
        <label htmlFor={ids.domain}>Domain</label>{" "}
        <input id={ids.domain} name="domain_id" defaultValue={domainId} />{" "}
        <button type="submit">Apply</button> <label htmlFor={ids.days}>Days</label>{" "}
        <select
          id={ids.days}
          value={effectiveDays}
          onChange={(e) => update("days", e.target.value)}
        >
          {DAY_OPTIONS.filter((d) => grain === "day" || d <= HOUR_MAX_DAYS).map((d) => (
            <option key={d} value={d}>
              {d}
            </option>
          ))}
        </select>{" "}
        <label htmlFor={ids.grain}>Grain</label>{" "}
        <select id={ids.grain} value={grain} onChange={(e) => update("grain", e.target.value)}>
          <option value="day">day</option>
          <option value="hour">hour</option>
        </select>
      </form>
      {domainId === "" ? (
        <p data-testid="domain-required">Choose a domain to view this dashboard.</p>
      ) : (
        metrics.map((m) => (
          <MetricSection
            key={m}
            metric={m}
            domainId={domainId}
            days={effectiveDays}
            grain={grain}
            title={title}
          />
        ))
      )}
    </section>
  );
}
