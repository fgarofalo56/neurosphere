import { Button, Field, Input, makeStyles, tokens } from "@fluentui/react-components";
import { useState, type ReactElement } from "react";
import { useSearchParams } from "react-router";
import { useSelectedDomain } from "../../app/domain";
import {
  BarChart,
  EmptyState,
  KpiCard,
  LoadingState,
  PageTemplate,
  Panel,
  Timestamp,
  type ChartSeries,
  type HealthState,
} from "../../design-system";
import {
  CalibrationBadge,
  PilotRate,
  QueryErrorState,
  intervalText,
  judgeText,
} from "./components";
import { useQuality } from "./hooks";
import { STRINGS, fractionText, numberText, orUnknown } from "./strings";
import type { QualityResponse, Trend } from "./types";
import { useTableClasses } from "./tableClasses";

/** One bar series per judge configuration, so differently judged scores are never merged. */
function trendSeries(trend: Trend): readonly ChartSeries[] {
  const byJudge = new Map<string, ChartSeries["points"][number][]>();
  for (const p of trend.points) {
    const key = judgeText(p.judge);
    const list = byJudge.get(key) ?? [];
    list.push({ t: p.bucket_start, value: p.value });
    byJudge.set(key, list);
  }
  return [...byJudge.entries()].map(([key, points]) => ({
    key,
    label: key,
    kind: null,
    unit: "ratio" as const,
    currency: null,
    points,
  }));
}

function Trends({ data }: { readonly data: QualityResponse }): ReactElement {
  const H = STRINGS.trendHeaders;
  const t = useTableClasses();
  return (
    <Panel landmark="region" title={STRINGS.sections.trends}>
      {data.trends.length === 0 ? (
        <div data-testid="trends-empty">
          <EmptyState title={STRINGS.noTrends} />
        </div>
      ) : null}
      {data.trends.map((trend) => (
        <div key={trend.dimension} className={t.wrap}>
          {trend.points.length > 0 ? (
            <BarChart
              series={trendSeries(trend)}
              ariaLabel={`${trend.dimension} score by period`}
              height={180}
            />
          ) : null}
          <table className={t.table} data-testid={`trend-${trend.dimension}`}>
            <caption className={t.caption}>{trend.dimension}</caption>
            <thead>
              <tr>
                <th className={t.th} scope="col">
                  {H.bucket}
                </th>
                <th className={t.th} scope="col">
                  {H.value}
                </th>
                <th className={t.th} scope="col">
                  {H.interval}
                </th>
                <th className={t.th} scope="col">
                  {H.n}
                </th>
                <th className={t.th} scope="col">
                  {H.judge}
                </th>
                <th className={t.th} scope="col">
                  {H.calibration}
                </th>
              </tr>
            </thead>
            <tbody>
              {trend.points.map((p) => (
                // The API emits one point per judge per UTC day, so the bucket alone is not unique.
                <tr key={`${p.bucket_start}|${judgeText(p.judge)}`} data-testid="trend-row">
                  <th className={t.td} scope="row">
                    <Timestamp value={p.bucket_start} grain="day" />
                  </th>
                  <td className={t.td} data-testid="trend-value">
                    {numberText(p.value)}
                  </td>
                  <td className={t.td}>{intervalText(p.lower, p.upper, p.level)}</td>
                  <td className={t.td}>{p.sample_size}</td>
                  <td className={t.td} data-testid="trend-judge">
                    {judgeText(p.judge)}
                  </td>
                  <td className={t.td}>
                    <CalibrationBadge state={p.calibration_state} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ))}
    </Panel>
  );
}

function Kpis({ data }: { readonly data: QualityResponse }): ReactElement {
  const rate = data.pilot_grounded_rate;
  const estimable = rate.method === "wilson_score" && rate.value !== null;
  const rateStatus: HealthState =
    !estimable || rate.value === null ? "unknown" : rate.value >= rate.target ? "ok" : "degraded";
  const drift = data.drift_alerts.length;
  return (
    <>
      <KpiCard
        label={STRINGS.pilot.title}
        value={estimable ? fractionText(rate.value) : STRINGS.unknown}
        status={rateStatus}
      />
      <KpiCard label={STRINGS.pilot.sampleSize} value={String(rate.n)} />
      <KpiCard
        label={STRINGS.labelHeaders.missing}
        value={orUnknown(data.missing_labels.missing)}
      />
      <KpiCard
        label={STRINGS.sections.drift}
        value={String(drift)}
        status={drift === 0 ? "ok" : "degraded"}
      />
    </>
  );
}

function Body({ data }: { readonly data: QualityResponse }): ReactElement {
  const C = STRINGS.coverageHeaders;
  const L = STRINGS.labelHeaders;
  const D = STRINGS.driftHeaders;
  const t = useTableClasses();
  return (
    <>
      <PilotRate rate={data.pilot_grounded_rate} />
      <Trends data={data} />
      <Panel landmark="region" title={STRINGS.sections.coverage}>
        {data.coverage.length === 0 ? (
          <EmptyState title={STRINGS.noCoverage} />
        ) : (
          <div className={t.wrap}>
            <table className={t.table} aria-label={STRINGS.sections.coverage}>
              <thead>
                <tr>
                  <th className={t.th} scope="col">
                    {C.stratum}
                  </th>
                  <th className={t.th} scope="col">
                    {C.sampled}
                  </th>
                  <th className={t.th} scope="col">
                    {C.population}
                  </th>
                  <th className={t.th} scope="col">
                    {C.fraction}
                  </th>
                </tr>
              </thead>
              <tbody>
                {data.coverage.map((c) => (
                  <tr key={c.stratum} data-testid="coverage-row">
                    <th className={t.td} scope="row">
                      {c.stratum}
                    </th>
                    <td className={t.td}>{c.sampled}</td>
                    <td className={t.td}>{orUnknown(c.population)}</td>
                    <td className={t.td} data-testid="coverage-fraction">
                      {fractionText(c.coverage_fraction)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Panel>
      <Panel landmark="region" title={STRINGS.sections.labels}>
        <div className={t.wrap}>
          <table className={t.table} aria-label={STRINGS.sections.labels}>
            <thead>
              <tr>
                <th className={t.th} scope="col">
                  {L.judged}
                </th>
                <th className={t.th} scope="col">
                  {L.labelled}
                </th>
                <th className={t.th} scope="col">
                  {L.missing}
                </th>
              </tr>
            </thead>
            <tbody>
              <tr data-testid="label-row">
                <td className={t.td}>{orUnknown(data.missing_labels.judged)}</td>
                <td className={t.td}>{orUnknown(data.missing_labels.labelled)}</td>
                <td className={t.td} data-testid="missing-labels">
                  {orUnknown(data.missing_labels.missing)}
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </Panel>
      <Panel landmark="region" title={STRINGS.sections.drift}>
        {data.drift_alerts.length === 0 ? (
          <div data-testid="drift-empty">
            <EmptyState title={STRINGS.noDrift} />
          </div>
        ) : (
          <div className={t.wrap}>
            <table className={t.table} aria-label={STRINGS.sections.drift}>
              <thead>
                <tr>
                  <th className={t.th} scope="col">
                    {D.dimension}
                  </th>
                  <th className={t.th} scope="col">
                    {D.subject}
                  </th>
                  <th className={t.th} scope="col">
                    {D.detected}
                  </th>
                  <th className={t.th} scope="col">
                    {D.statistic}
                  </th>
                  <th className={t.th} scope="col">
                    {D.threshold}
                  </th>
                </tr>
              </thead>
              <tbody>
                {data.drift_alerts.map((a) => (
                  <tr
                    key={`${a.subject_id}|${a.dimension}|${a.detected_at}`}
                    data-testid="drift-row"
                  >
                    <td className={t.td}>{a.dimension}</td>
                    <td className={t.td}>{a.subject_id}</td>
                    <td className={t.td}>
                      <Timestamp value={a.detected_at} />
                    </td>
                    <td className={t.td}>{numberText(a.statistic)}</td>
                    <td className={t.td}>{numberText(a.threshold)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Panel>
    </>
  );
}

const useStyles = makeStyles({
  form: {
    display: "flex",
    flexWrap: "wrap",
    alignItems: "flex-end",
    columnGap: tokens.spacingHorizontalM,
    rowGap: tokens.spacingVerticalS,
  },
});

function QualityFilters({ subjectId }: { readonly subjectId: string }): ReactElement {
  const styles = useStyles();
  const [, setParams] = useSearchParams();
  const [subject, setSubject] = useState(subjectId);
  return (
    <form
      aria-label="Quality filters"
      className={styles.form}
      onSubmit={(e) => {
        e.preventDefault();
        setParams((prev) => {
          const next = new URLSearchParams(prev);
          const v = subject.trim();
          if (v === "") next.delete("subject_id");
          else next.set("subject_id", v);
          return next;
        });
      }}
    >
      <Field label={STRINGS.subjectLabel}>
        <Input value={subject} onChange={(_e, data) => setSubject(data.value)} />
      </Field>
      <Button type="submit" appearance="primary">
        {STRINGS.apply}
      </Button>
    </form>
  );
}

function QualityView({
  domainId,
  subjectId,
}: {
  readonly domainId: string;
  readonly subjectId: string;
}): ReactElement {
  const query = useQuality({ domainId, subjectId });
  const data = query.data;
  return (
    <PageTemplate
      title={STRINGS.title}
      toolbar={<QualityFilters key={subjectId} subjectId={subjectId} />}
      toolbarLabel="Quality filters"
      busy={query.isPending}
      kpis={data === undefined ? undefined : <Kpis data={data} />}
    >
      {query.isError ? (
        <QueryErrorState error={query.error} />
      ) : data === undefined ? (
        <div aria-busy="true">
          <LoadingState label={STRINGS.loading} />
        </div>
      ) : (
        <Body data={data} />
      )}
    </PageTemplate>
  );
}

export function QualityPage(): ReactElement {
  const [params] = useSearchParams();
  const { domainId } = useSelectedDomain();
  const subjectId = params.get("subject_id") ?? "";
  if (domainId === "") {
    return (
      <PageTemplate
        title={STRINGS.title}
        toolbar={<QualityFilters key={subjectId} subjectId={subjectId} />}
        toolbarLabel="Quality filters"
      >
        <div data-testid="domain-required">
          <EmptyState title={STRINGS.domainRequired} />
        </div>
      </PageTemplate>
    );
  }
  return <QualityView key={`${domainId}|${subjectId}`} domainId={domainId} subjectId={subjectId} />;
}
