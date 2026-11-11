import { makeStyles, tokens } from "@fluentui/react-components";
import type { ReactElement } from "react";
import { LoadingState, Panel, Timestamp } from "../../design-system";
import { QueryErrorState } from "./components";
import { useCalibrationSample } from "./hooks";
import { STRINGS, orUnknown } from "./strings";
import type { CalibrationSampleView } from "./types";

const useStyles = makeStyles({
  payload: {
    margin: 0,
    padding: tokens.spacingVerticalS,
    overflowX: "auto",
    maxHeight: "20rem",
    backgroundColor: tokens.colorNeutralBackground3,
    fontFamily: tokens.fontFamilyMonospace,
    fontSize: tokens.fontSizeBase200,
  },
});

/** 1 = pass, 0 = fail. The verdict is spelled out; any other value is shown as is. */
export function verdictWords(value: number): string {
  const D = STRINGS.dispute;
  if (value === 1) return D.verdictPass;
  if (value === 0) return D.verdictFail;
  return String(value);
}

function withheldText(reason: string | null): string {
  const D = STRINGS.dispute;
  return reason === null || reason === "restricted" ? D.withheld : D.withheldOther(reason);
}

function SampleDetails({ sample }: { readonly sample: CalibrationSampleView }): ReactElement {
  const styles = useStyles();
  const D = STRINGS.dispute;
  return (
    <>
      <p data-testid="dispute-instruction">
        <strong>{D.instruction}</strong>
      </p>
      <dl>
        <dt>{D.item}</dt>
        <dd data-testid="dispute-item">{sample.item_id}</dd>
        <dt>{D.dataset}</dt>
        <dd data-testid="dispute-dataset">
          {sample.dataset_id === null
            ? STRINGS.unknown
            : `${sample.dataset_id} ${orUnknown(sample.dataset_version)}`}
        </dd>
        <dt>{D.dimension}</dt>
        <dd data-testid="dispute-dimension">{sample.dimension}</dd>
        <dt>{D.verdict}</dt>
        <dd data-testid="dispute-verdict">{verdictWords(sample.value)}</dd>
        <dt>{D.judge}</dt>
        <dd data-testid="dispute-judge">
          {sample.judge_config_id} {sample.judge_config_version}
        </dd>
        <dt>{D.rubric}</dt>
        <dd data-testid="dispute-rubric">
          {sample.rubric_id} {sample.rubric_version}
        </dd>
        <dt>{D.classification}</dt>
        <dd data-testid="dispute-classification">{orUnknown(sample.classification)}</dd>
        <dt>{D.opened}</dt>
        <dd>
          <Timestamp value={sample.opened_at} />
        </dd>
      </dl>
      <div role="group" aria-label={D.content} data-testid="dispute-content">
        {sample.payload === null || sample.payload_withheld ? (
          <p data-testid="dispute-withheld">{withheldText(sample.withheld_reason)}</p>
        ) : (
          <pre className={styles.payload} tabIndex={0} data-testid="dispute-payload">
            {JSON.stringify(sample.payload, null, 2)}
          </pre>
        )}
      </div>
    </>
  );
}

/**
 * The context of an `evaluation_dispute` review item: which dataset item, which judge verdict, and
 * what Approve / Reject mean. Rendered only for that kind; other kinds never mount this.
 */
export function CalibrationContext({
  domainId,
  subjectRef,
}: {
  readonly domainId: string;
  readonly subjectRef: string;
}): ReactElement {
  const query = useCalibrationSample({ domainId, subjectRef });
  const D = STRINGS.dispute;
  let body: ReactElement;
  if (query.isError) {
    // A 404 is "nothing recorded" (plain text, not an error state); anything else is retryable.
    body =
      query.error.status === 404 ? (
        <p data-testid="dispute-none">{D.none}</p>
      ) : (
        <QueryErrorState
          error={query.error}
          item
          onRetry={() => {
            void query.refetch();
          }}
        />
      );
  } else if (query.isPending) {
    body = (
      <div aria-busy="true" data-testid="dispute-loading">
        <LoadingState label={D.loading} rows={3} />
      </div>
    );
  } else {
    body = <SampleDetails sample={query.data} />;
  }
  return (
    <Panel title={D.title} landmark="region" testId="calibration-context">
      {body}
    </Panel>
  );
}
