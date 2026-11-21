import { Button, Field, Textarea, makeStyles, tokens } from "@fluentui/react-components";
import { useState, type ReactElement } from "react";
import { useSelectedDomain } from "../../../app/domain";
import { EmptyState, LoadingState, PageTemplate } from "../../../design-system";
import type { ApiError } from "../../../api/index.js";
import { QueryErrorState } from "../components";
import { useAgentMatch } from "./hooks";
import { MatchCandidateCard } from "./MatchCandidateCard";
import { MatchMetricsStrip } from "./MatchMetricsStrip";
import { MATCH_STRINGS, PARTIAL_REASON_LABELS, SIGNAL_LABELS, resultCountText } from "./strings";
import { joinAssessments, type AgentMatchView, type FeedbackDecision } from "./types";

const MIN_TASK = 3;
const MAX_TASK = 2000;

const useStyles = makeStyles({
  form: {
    display: "flex",
    flexDirection: "column",
    rowGap: tokens.spacingVerticalS,
    maxWidth: "720px",
  },
  grid: {
    display: "grid",
    gridTemplateColumns: "repeat(auto-fill, minmax(420px, 1fr))",
    columnGap: tokens.spacingHorizontalL,
    rowGap: tokens.spacingVerticalL,
    margin: 0,
    padding: 0,
  },
  banner: {
    padding: tokens.spacingHorizontalM,
    border: `${tokens.strokeWidthThin} solid ${tokens.colorNeutralStroke1}`,
    borderRadius: tokens.borderRadiusMedium,
    margin: 0,
  },
  hint: { color: tokens.colorNeutralForeground2, fontSize: tokens.fontSizeBase200 },
  visuallyHidden: {
    position: "absolute",
    width: "1px",
    height: "1px",
    overflow: "hidden",
    clip: "rect(0 0 0 0)",
    whiteSpace: "nowrap",
  },
});

function statusText(view: AgentMatchView | undefined): string {
  if (view === undefined) return "";
  const count = resultCountText(view.match.candidates.length);
  const partial = view.match.truncated || (view.match.partial_reason ?? null) !== null;
  return partial ? `${count}. ${MATCH_STRINGS.partialResults}` : count;
}

function MatchError({ error }: { readonly error: ApiError }): ReactElement {
  const reason = error.problem?.reason ?? error.problem?.code ?? error.code;
  return (
    <>
      <QueryErrorState error={error} />
      <p data-testid="match-error-reason">
        {MATCH_STRINGS.reasonCode}: {reason}
      </p>
    </>
  );
}

function Banners({ view }: { readonly view: AgentMatchView }): ReactElement {
  const styles = useStyles();
  const { match } = view;
  const partialReason = match.partial_reason ?? null;
  const partial = match.truncated || partialReason !== null;
  const unobserved = match.signals_unavailable;
  return (
    <>
      {partial ? (
        <p className={styles.banner} data-testid="match-partial">
          <strong>{MATCH_STRINGS.partialBanner}</strong>{" "}
          {partialReason === null ? "" : PARTIAL_REASON_LABELS[partialReason]}
        </p>
      ) : null}
      {match.cold_start || unobserved.length > 0 ? (
        <p className={styles.banner} data-testid="match-cold-start-banner">
          <strong>{MATCH_STRINGS.coldStartBanner}</strong>
          {unobserved.length > 0
            ? `: ${unobserved.map((s) => SIGNAL_LABELS[s]).join(", ")}. `
            : ". "}
          {MATCH_STRINGS.unobservedDetail}
        </p>
      ) : null}
      <p className={styles.hint} data-testid="match-confidence-note">
        {view.confidence_note}
      </p>
    </>
  );
}

function Results({
  view,
  domainId,
}: {
  readonly view: AgentMatchView;
  readonly domainId: string;
}): ReactElement {
  const styles = useStyles();
  const matchId = view.match.match_id;
  // Decisions live in page memory for the current match only.
  const [decided, setDecided] = useState<{
    readonly matchId: string;
    readonly byEntity: Readonly<Record<string, FeedbackDecision>>;
  }>({ matchId, byEntity: {} });
  const byEntity = decided.matchId === matchId ? decided.byEntity : {};
  const items = joinAssessments(view);

  function confirmed(entityId: string, decision: FeedbackDecision): void {
    setDecided({ matchId, byEntity: { ...byEntity, [entityId]: decision } });
  }

  return (
    <>
      <Banners view={view} />
      {items.length === 0 ? (
        <div data-testid="match-empty">
          <EmptyState title={MATCH_STRINGS.emptyState} />
        </div>
      ) : (
        <ul aria-label={MATCH_STRINGS.resultsLabel} className={styles.grid}>
          {items.map((item) => (
            <MatchCandidateCard
              key={`${matchId}|${item.candidate.entity_id}`}
              item={item}
              domainId={domainId}
              matchId={matchId}
              decision={byEntity[item.candidate.entity_id]}
              onConfirmed={confirmed}
            />
          ))}
        </ul>
      )}
    </>
  );
}

function FindAgentBody({ domainId }: { readonly domainId: string }): ReactElement {
  const styles = useStyles();
  const [task, setTask] = useState("");
  const match = useAgentMatch();
  const trimmed = task.trim();
  const canSubmit = trimmed.length >= MIN_TASK && !match.isPending;

  return (
    <>
      <form
        aria-label={MATCH_STRINGS.title}
        className={styles.form}
        onSubmit={(e) => {
          e.preventDefault();
          if (!canSubmit) return;
          match.mutate({
            domainId,
            request: { schema_version: "1.0.0", task_text: trimmed },
          });
        }}
      >
        <Field label={MATCH_STRINGS.taskLabel} hint={MATCH_STRINGS.taskHint}>
          <Textarea
            data-testid="match-task-input"
            value={task}
            maxLength={MAX_TASK}
            resize="vertical"
            onChange={(_e, data) => setTask(data.value)}
          />
        </Field>
        <div>
          <Button
            type="submit"
            appearance="primary"
            data-testid="match-submit"
            disabledFocusable={!canSubmit}
          >
            {match.isPending ? MATCH_STRINGS.submitting : MATCH_STRINGS.submit}
          </Button>
        </div>
      </form>
      <div
        role="status"
        aria-live="polite"
        data-testid="match-status"
        className={styles.visuallyHidden}
      >
        {statusText(match.data)}
      </div>
      {match.isPending ? (
        <div aria-busy="true">
          <LoadingState label={MATCH_STRINGS.loading} />
        </div>
      ) : null}
      {match.isError ? <MatchError error={match.error} /> : null}
      {match.isSuccess ? <Results view={match.data} domainId={domainId} /> : null}
      <MatchMetricsStrip domainId={domainId} />
    </>
  );
}

/** Find an agent: describe a task, read the ranked explanation, accept or reject. */
export function FindAgentPage(): ReactElement {
  const { domainId } = useSelectedDomain();
  return (
    <PageTemplate title={MATCH_STRINGS.title} data-testid="find-agent-page">
      {domainId === "" ? (
        <div data-testid="domain-required">
          <EmptyState title={MATCH_STRINGS.domainRequired} />
        </div>
      ) : (
        <FindAgentBody key={domainId} domainId={domainId} />
      )}
    </PageTemplate>
  );
}
