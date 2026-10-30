import {
  Button,
  Dropdown,
  Field,
  Input,
  Option,
  makeStyles,
  tokens,
} from "@fluentui/react-components";
import { useId, useState, type ReactElement } from "react";
import { Link } from "react-router";
import { ForbiddenError } from "../../api/index.js";
import { useSelectedDomain } from "../../app/domain";
import {
  DataTable,
  EmptyState,
  ErrorState,
  LoadingState,
  PageTemplate,
  StatusPill,
  Timestamp,
  type DataTableColumn,
  type StatusTone,
} from "../../design-system";
import { ForbiddenState } from "../workspaces/ForbiddenState";
import { useEvaluationResults, type EvaluationFilters } from "./data";
import { STRINGS } from "./strings";
import { EVALUATION_DIMENSIONS, type EvaluationResult, type EvaluationScore } from "./types";

const useStyles = makeStyles({
  row: {
    display: "flex",
    alignItems: "flex-end",
    columnGap: tokens.spacingHorizontalM,
    flexWrap: "wrap",
  },
  stack: { display: "flex", flexDirection: "column", rowGap: tokens.spacingVerticalM },
  muted: { color: tokens.colorNeutralForeground2, fontSize: tokens.fontSizeBase200 },
  subjectInput: { minWidth: "320px" },
  dropdown: { minWidth: "220px" },
});

/** One table row per score: a result carries one score per dimension. */
interface ScoreRow {
  readonly id: string;
  readonly result: EvaluationResult;
  readonly score: EvaluationScore;
}

function toRows(results: readonly EvaluationResult[]): readonly ScoreRow[] {
  return results.flatMap((result) =>
    result.scores.map((score) => ({
      id: `${result.evaluation_id}:${score.dimension}`,
      result,
      score,
    })),
  );
}

/** Judge identity exactly as returned; absent parts are left out, not guessed. */
export function judgeText(result: EvaluationResult): string {
  const j = result.judge;
  const parts = [j.judge_model_id, j.judge_model_version, j.judge_prompt_version, j.program_version]
    .filter((p): p is string => typeof p === "string" && p !== "")
    .join(" ");
  return parts === "" ? j.judge_kind : `${j.judge_kind}: ${parts}`;
}

export function calibrationText(result: EvaluationResult): string {
  const c = result.calibration;
  if (c === null) return STRINGS.noCalibration;
  return STRINGS.calibrationText(
    c.agreement.metric,
    c.agreement.value,
    c.agreement.sample_size,
    c.calibrated_at,
  );
}

/** Every uncertainty field the API sent, unrounded. */
export function uncertaintyText(score: EvaluationScore): string {
  const u = score.uncertainty;
  if (u.method === "not_estimable") return STRINGS.uncertaintyNotEstimable;
  const parts: string[] = [u.method.replaceAll("_", " ")];
  if (u.lower != null && u.upper != null) parts.push(`${u.lower} to ${u.upper}`);
  if (u.level != null) parts.push(`level ${u.level}`);
  if (u.standard_error != null) parts.push(`standard error ${u.standard_error}`);
  return parts.join(", ");
}

function statusTone(status: EvaluationResult["status"]): StatusTone {
  if (status === "completed") return "success";
  return status === "partial" ? "warning" : "danger";
}

function columns(): readonly DataTableColumn<ScoreRow>[] {
  const c = STRINGS.columns;
  return [
    {
      key: "time",
      header: c.time,
      render: (r) => <Timestamp value={r.result.completed_at} />,
    },
    { key: "subject", header: c.subject, render: (r) => r.result.subject_id },
    { key: "dimension", header: c.dimension, render: (r) => r.score.dimension },
    {
      key: "score",
      header: c.score,
      render: (r) =>
        r.score.value === null
          ? STRINGS.notScored
          : STRINGS.scoreText(r.score.value, r.score.scale.min, r.score.scale.max),
    },
    { key: "sample", header: c.sample, render: (r) => r.score.sample_size },
    { key: "judge", header: c.judge, render: (r) => judgeText(r.result) },
    { key: "calibration", header: c.calibration, render: (r) => calibrationText(r.result) },
    { key: "uncertainty", header: c.uncertainty, render: (r) => uncertaintyText(r.score) },
    {
      key: "status",
      header: c.status,
      render: (r) => <StatusPill label={r.result.status} tone={statusTone(r.result.status)} />,
    },
  ];
}

function Results({
  domain,
  filters,
}: {
  readonly domain: string;
  readonly filters: EvaluationFilters;
}): ReactElement {
  const styles = useStyles();
  const q = useEvaluationResults(domain, filters);
  if (q.isPending) return <LoadingState label={STRINGS.loading} rows={5} />;
  if (q.isError) {
    if (q.error instanceof ForbiddenError) {
      return (
        <ForbiddenState
          workspace={STRINGS.forbiddenWorkspace}
          correlationId={q.error.correlationId}
        />
      );
    }
    return (
      <ErrorState
        title={STRINGS.failedTitle}
        message={q.error.correlationId === "" ? undefined : `Reference: ${q.error.correlationId}.`}
        testId="evaluations-error"
        onRetry={() => void q.refetch()}
      />
    );
  }
  const results = q.data.flatMap((p) => p.items);
  const rows = toRows(results);
  if (rows.length === 0) {
    return (
      <EmptyState
        title={STRINGS.emptyTitle}
        description={STRINGS.emptyBody}
        testId="evaluations-empty"
      />
    );
  }
  return (
    <div className={styles.stack}>
      <DataTable
        label={STRINGS.tableLabel}
        columns={columns()}
        rows={rows}
        getRowId={(r) => r.id}
        getRowProps={(r) => ({
          "data-testid": "evaluation-row",
          "data-dimension": r.score.dimension,
          "data-subject": r.result.subject_id,
        })}
      />
      {q.hasNextPage ? (
        <div className={styles.row}>
          <span className={styles.muted} data-testid="evaluations-count">
            {STRINGS.moreNote(results.length)}
          </span>
          <Button
            disabled={q.isFetchingNextPage}
            onClick={() => void q.fetchNextPage()}
            data-testid="evaluations-more"
          >
            {q.isFetchingNextPage ? STRINGS.loadingMore : STRINGS.loadMore}
          </Button>
        </div>
      ) : (
        <span className={styles.muted} data-testid="evaluations-count">
          {STRINGS.endNote(results.length)}
        </span>
      )}
    </div>
  );
}

const ALL = "";

/**
 * Evaluation results for the selected domain. Filters apply on submit (no request per
 * keystroke). The domain is a path segment only; subject and dimension are the only query keys.
 */
export function EvaluationsPage(): ReactElement {
  const styles = useStyles();
  const { domainId } = useSelectedDomain();
  const subjectId = useId();
  const [draftSubject, setDraftSubject] = useState("");
  const [draftDimension, setDraftDimension] = useState(ALL);
  const [filters, setFilters] = useState<EvaluationFilters>({ subjectId: "", dimension: ALL });

  const apply = (): void =>
    setFilters({ subjectId: draftSubject.trim(), dimension: draftDimension });
  const clear = (): void => {
    setDraftSubject("");
    setDraftDimension(ALL);
    setFilters({ subjectId: "", dimension: ALL });
  };

  const toolbar = (
    <form
      className={styles.row}
      onSubmit={(e) => {
        e.preventDefault();
        apply();
      }}
    >
      <Field label={STRINGS.subjectLabel}>
        <Input
          id={subjectId}
          className={styles.subjectInput}
          value={draftSubject}
          onChange={(_e, data) => setDraftSubject(data.value)}
        />
      </Field>
      <Field label={STRINGS.dimensionLabel}>
        <Dropdown
          className={styles.dropdown}
          value={draftDimension === ALL ? STRINGS.dimensionAll : draftDimension}
          selectedOptions={[draftDimension]}
          onOptionSelect={(_e, option) => setDraftDimension(option.optionValue ?? ALL)}
        >
          <Option value={ALL} text={STRINGS.dimensionAll}>
            {STRINGS.dimensionAll}
          </Option>
          {EVALUATION_DIMENSIONS.map((d) => (
            <Option key={d} value={d} text={d}>
              {d}
            </Option>
          ))}
        </Dropdown>
      </Field>
      <Button appearance="primary" type="submit" data-testid="evaluations-apply">
        {STRINGS.apply}
      </Button>
      <Button onClick={clear} data-testid="evaluations-clear">
        {STRINGS.clear}
      </Button>
    </form>
  );

  return (
    <PageTemplate
      title={STRINGS.pageTitle}
      description={STRINGS.pageDescription}
      data-testid="evaluations-page"
      toolbar={toolbar}
      toolbarLabel="Evaluation filters"
      actions={
        <Link
          to={{ pathname: "/quality", search: `?domain_id=${encodeURIComponent(domainId)}` }}
          data-testid="evaluations-quality-link"
        >
          {STRINGS.qualityLink}
        </Link>
      }
    >
      {domainId === "" ? (
        <EmptyState title={STRINGS.noDomainTitle} description={STRINGS.noDomainBody} />
      ) : (
        <Results key={`${domainId}`} domain={domainId} filters={filters} />
      )}
    </PageTemplate>
  );
}
