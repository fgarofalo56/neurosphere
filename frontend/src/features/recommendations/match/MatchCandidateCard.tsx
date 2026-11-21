import { Button, makeStyles, mergeClasses, tokens } from "@fluentui/react-components";
import { useRef, type ReactElement } from "react";
import { Link } from "react-router";
import { StatusPill, useUiStyle } from "../../../design-system";
import { CATALOG_ENTITY_ROUTE } from "../../catalog/paths";
import { MAP_PATH } from "../../map/paths";
import { ExplanationList } from "./ExplanationList";
import { useMatchFeedback } from "./hooks";
import { MATCH_STRINGS } from "./strings";
import type { FeedbackDecision, JoinedCandidate } from "./types";
import { formatRatio } from "./types";

const useStyles = makeStyles({
  card: {
    display: "flex",
    flexDirection: "column",
    rowGap: tokens.spacingVerticalS,
    minWidth: 0,
    boxSizing: "border-box",
    padding: tokens.spacingHorizontalL,
    listStyleType: "none",
    backgroundColor: tokens.colorNeutralBackground1,
    border: `${tokens.strokeWidthThin} solid ${tokens.colorNeutralStroke2}`,
  },
  lifted: { backgroundColor: tokens.colorNeutralBackground2 },
  raised: { boxShadow: tokens.shadow4 },
  radiusSmall: { borderRadius: tokens.borderRadiusSmall },
  radiusMedium: { borderRadius: tokens.borderRadiusMedium },
  head: {
    display: "flex",
    flexWrap: "wrap",
    alignItems: "center",
    columnGap: tokens.spacingHorizontalM,
    rowGap: tokens.spacingVerticalXS,
  },
  title: { margin: 0, fontSize: tokens.fontSizeBase400, fontWeight: tokens.fontWeightSemibold },
  facts: {
    display: "grid",
    gridTemplateColumns: "max-content 1fr",
    columnGap: tokens.spacingHorizontalL,
    rowGap: tokens.spacingVerticalXXS,
    margin: 0,
  },
  term: { color: tokens.colorNeutralForeground2 },
  def: { margin: 0, overflowWrap: "anywhere" },
  actions: { display: "flex", flexWrap: "wrap", columnGap: tokens.spacingHorizontalS },
  list: { margin: 0, paddingLeft: tokens.spacingHorizontalL, overflowWrap: "anywhere" },
});

export function entityHref(entityId: string): string {
  return `/${CATALOG_ENTITY_ROUTE}?${new URLSearchParams({ entity_id: entityId }).toString()}`;
}

export function mapHref(domainId: string): string {
  return `${MAP_PATH}?${new URLSearchParams({ domain_id: domainId }).toString()}`;
}

function listText(values: readonly string[]): string {
  return values.length === 0 ? MATCH_STRINGS.noneText : values.join(", ");
}

/**
 * One ranked candidate. Accept and Reject post once; the stored state changes only after the
 * 202 (`onConfirmed`), a failure keeps the previous decision and shows its error here.
 */
export function MatchCandidateCard({
  item,
  domainId,
  matchId,
  decision,
  onConfirmed,
}: {
  readonly item: JoinedCandidate;
  readonly domainId: string;
  readonly matchId: string;
  readonly decision: FeedbackDecision | undefined;
  readonly onConfirmed: (entityId: string, decision: FeedbackDecision) => void;
}): ReactElement {
  const styles = useStyles();
  const { treatment } = useUiStyle();
  const ref = useRef<HTMLLIElement>(null);
  const feedback = useMatchFeedback();
  const { candidate, assessment } = item;
  const S = MATCH_STRINGS;

  function keepFocus(): void {
    const active = document.activeElement;
    if (active === null || active === document.body || !ref.current?.contains(active)) {
      ref.current?.focus();
    }
  }

  function decide(next: FeedbackDecision): void {
    if (feedback.isPending || next === decision) return;
    feedback.mutate(
      {
        domainId,
        request: {
          schema_version: "1.0.0",
          match_id: matchId,
          entity_id: candidate.entity_id,
          decision: next,
        },
      },
      {
        onSuccess: () => {
          onConfirmed(candidate.entity_id, next);
          keepFocus();
        },
        onError: keepFocus,
      },
    );
  }

  const state =
    decision === "accepted" ? S.accepted : decision === "rejected" ? S.rejected : S.noDecision;
  const nameId = `match-name-${String(candidate.rank)}`;

  return (
    <li
      ref={ref}
      tabIndex={-1}
      aria-labelledby={nameId}
      data-testid="match-candidate"
      data-entity-id={candidate.entity_id}
      data-slot="match-candidate-card"
      className={mergeClasses(
        styles.card,
        treatment.panelSurface === "lifted" && styles.lifted,
        treatment.surface === "raised" && styles.raised,
        treatment.radius === "small" ? styles.radiusSmall : styles.radiusMedium,
      )}
    >
      <div className={styles.head}>
        <h2 id={nameId} className={styles.title}>
          {candidate.display_name}
        </h2>
        <StatusPill label={S.kind[candidate.entity_type]} tone="info" />
        {assessment?.cold_start === true ? (
          <span data-testid="match-cold-start">
            <StatusPill label={S.coldStartLabel} tone="warning" />
          </span>
        ) : null}
      </div>
      {assessment?.cold_start === true ? <small>{S.coldStart}</small> : null}
      <dl className={styles.facts}>
        <dt className={styles.term}>{S.score}</dt>
        <dd className={styles.def} data-testid="match-score">
          {formatRatio(candidate.score)}
        </dd>
        <dt className={styles.term}>{S.confidenceLabel}</dt>
        <dd className={styles.def} data-testid="match-confidence">
          {assessment === undefined ? S.notAvailable : formatRatio(assessment.confidence)}
        </dd>
        <dt className={styles.term}>{S.matchedCapabilities}</dt>
        <dd className={styles.def}>{listText(candidate.matched_capabilities)}</dd>
        <dt className={styles.term}>{S.matchedTags}</dt>
        <dd className={styles.def}>{listText(candidate.matched_tags)}</dd>
      </dl>
      <ExplanationList signals={candidate.signals} />
      <div>
        <strong>{S.relationships}</strong>
        {candidate.relations.length === 0 ? (
          <span data-testid="match-no-relations">: {S.noneText}</span>
        ) : (
          <ul className={styles.list} data-testid="match-relations">
            {candidate.relations.map((r) => (
              <li key={`${r.relation_type}|${r.direction}|${r.entity_id}`}>
                {r.relation_type} ({r.direction}){" "}
                <Link to={entityHref(r.entity_id)}>{r.entity_id}</Link>
              </li>
            ))}
          </ul>
        )}
      </div>
      <div className={styles.actions}>
        <Link to={entityHref(candidate.entity_id)}>{S.openInCatalog}</Link>
        <Link to={mapHref(domainId)}>{S.showOnMap}</Link>
      </div>
      <div
        className={styles.actions}
        role="group"
        aria-label={`${S.decisionLabel}: ${candidate.display_name}`}
      >
        <Button
          data-testid="match-accept"
          appearance={decision === "accepted" ? "primary" : "secondary"}
          aria-pressed={decision === "accepted"}
          disabledFocusable={feedback.isPending}
          onClick={() => decide("accepted")}
        >
          {S.accept}
        </Button>
        <Button
          data-testid="match-reject"
          appearance={decision === "rejected" ? "primary" : "secondary"}
          aria-pressed={decision === "rejected"}
          disabledFocusable={feedback.isPending}
          onClick={() => decide("rejected")}
        >
          {S.reject}
        </Button>
        <span data-testid="match-decision">{state}</span>
      </div>
      {feedback.isError ? (
        <p role="alert" data-testid="match-feedback-error">
          {S.feedbackFailed}
          {feedback.error.message !== "" ? `: ${feedback.error.message}` : ""}
        </p>
      ) : null}
    </li>
  );
}
