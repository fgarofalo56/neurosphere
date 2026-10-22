import { Button, Field, Input, makeStyles, tokens } from "@fluentui/react-components";
import { useState, type ReactElement } from "react";
import { useSearchParams } from "react-router";
import { useSelectedDomain } from "../../app/domain";
import { PageTemplate } from "../../design-system";
import {
  CalibrationBadge,
  PilotRate,
  QueryErrorState,
  intervalText,
  judgeText,
} from "./components";
import { useQuality } from "./hooks";
import { STRINGS, fractionText, numberText, orUnknown } from "./strings";
import type { QualityResponse } from "./types";

function Trends({ data }: { readonly data: QualityResponse }): ReactElement {
  const H = STRINGS.trendHeaders;
  return (
    <section aria-labelledby="trends-heading">
      <h2 id="trends-heading">{STRINGS.sections.trends}</h2>
      {data.trends.length === 0 ? <p data-testid="trends-empty">{STRINGS.noTrends}</p> : null}
      {data.trends.map((trend) => (
        <table key={trend.dimension} data-testid={`trend-${trend.dimension}`}>
          <caption>{trend.dimension}</caption>
          <thead>
            <tr>
              <th scope="col">{H.bucket}</th>
              <th scope="col">{H.value}</th>
              <th scope="col">{H.interval}</th>
              <th scope="col">{H.n}</th>
              <th scope="col">{H.judge}</th>
              <th scope="col">{H.calibration}</th>
            </tr>
          </thead>
          <tbody>
            {trend.points.map((p) => (
              // The API emits one point per judge per UTC day, so the bucket alone is not unique.
              <tr key={`${p.bucket_start}|${judgeText(p.judge)}`} data-testid="trend-row">
                <th scope="row">{p.bucket_start}</th>
                <td data-testid="trend-value">{numberText(p.value)}</td>
                <td>{intervalText(p.lower, p.upper, p.level)}</td>
                <td>{p.sample_size}</td>
                <td data-testid="trend-judge">{judgeText(p.judge)}</td>
                <td>
                  <CalibrationBadge state={p.calibration_state} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      ))}
    </section>
  );
}

function Body({
  domainId,
  subjectId,
}: {
  readonly domainId: string;
  readonly subjectId: string;
}): ReactElement {
  const query = useQuality({ domainId, subjectId });
  if (query.isError) return <QueryErrorState error={query.error} />;
  if (query.isPending) return <p aria-busy="true">{STRINGS.loading}</p>;
  const data = query.data;
  const C = STRINGS.coverageHeaders;
  const L = STRINGS.labelHeaders;
  const D = STRINGS.driftHeaders;
  return (
    <>
      <PilotRate rate={data.pilot_grounded_rate} />
      <Trends data={data} />
      <section aria-labelledby="coverage-heading">
        <h2 id="coverage-heading">{STRINGS.sections.coverage}</h2>
        {data.coverage.length === 0 ? (
          <p>{STRINGS.noCoverage}</p>
        ) : (
          <table aria-label={STRINGS.sections.coverage}>
            <thead>
              <tr>
                <th scope="col">{C.stratum}</th>
                <th scope="col">{C.sampled}</th>
                <th scope="col">{C.population}</th>
                <th scope="col">{C.fraction}</th>
              </tr>
            </thead>
            <tbody>
              {data.coverage.map((c) => (
                <tr key={c.stratum} data-testid="coverage-row">
                  <th scope="row">{c.stratum}</th>
                  <td>{c.sampled}</td>
                  <td>{orUnknown(c.population)}</td>
                  <td data-testid="coverage-fraction">{fractionText(c.coverage_fraction)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
      <section aria-labelledby="labels-heading">
        <h2 id="labels-heading">{STRINGS.sections.labels}</h2>
        <table aria-label={STRINGS.sections.labels}>
          <thead>
            <tr>
              <th scope="col">{L.judged}</th>
              <th scope="col">{L.labelled}</th>
              <th scope="col">{L.missing}</th>
            </tr>
          </thead>
          <tbody>
            <tr data-testid="label-row">
              <td>{orUnknown(data.missing_labels.judged)}</td>
              <td>{orUnknown(data.missing_labels.labelled)}</td>
              <td data-testid="missing-labels">{orUnknown(data.missing_labels.missing)}</td>
            </tr>
          </tbody>
        </table>
      </section>
      <section aria-labelledby="drift-heading">
        <h2 id="drift-heading">{STRINGS.sections.drift}</h2>
        {data.drift_alerts.length === 0 ? (
          <p data-testid="drift-empty">{STRINGS.noDrift}</p>
        ) : (
          <table aria-label={STRINGS.sections.drift}>
            <thead>
              <tr>
                <th scope="col">{D.dimension}</th>
                <th scope="col">{D.subject}</th>
                <th scope="col">{D.detected}</th>
                <th scope="col">{D.statistic}</th>
                <th scope="col">{D.threshold}</th>
              </tr>
            </thead>
            <tbody>
              {data.drift_alerts.map((a) => (
                <tr key={`${a.subject_id}|${a.dimension}|${a.detected_at}`} data-testid="drift-row">
                  <td>{a.dimension}</td>
                  <td>{a.subject_id}</td>
                  <td>{a.detected_at}</td>
                  <td>{numberText(a.statistic)}</td>
                  <td>{numberText(a.threshold)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
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

export function QualityPage(): ReactElement {
  const [params] = useSearchParams();
  const { domainId } = useSelectedDomain();
  const subjectId = params.get("subject_id") ?? "";
  return (
    <PageTemplate
      title={STRINGS.title}
      toolbar={<QualityFilters key={subjectId} subjectId={subjectId} />}
      toolbarLabel="Quality filters"
    >
      {domainId === "" ? (
        <p data-testid="domain-required">{STRINGS.domainRequired}</p>
      ) : (
        <Body key={`${domainId}|${subjectId}`} domainId={domainId} subjectId={subjectId} />
      )}
    </PageTemplate>
  );
}
