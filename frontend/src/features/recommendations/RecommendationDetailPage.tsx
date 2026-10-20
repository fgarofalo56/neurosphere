import type { ReactElement } from "react";
import { Link, useSearchParams } from "react-router";
import {
  AdvisoryBadge,
  EstimateBlock,
  EvidenceStatus,
  QueryErrorState,
  coverageText,
  ownerText,
  uncertaintyText,
} from "./components";
import { useRecommendation, useRouteToReview } from "./hooks";
import { KIND_LABELS, STRINGS, orUnknown } from "./strings";
import type { RecommendationDetailResponse } from "./types";

function ReviewControl({
  domainId,
  data,
}: {
  readonly domainId: string;
  readonly data: RecommendationDetailResponse;
}): ReactElement {
  const mutation = useRouteToReview();
  const rec = data.recommendation;
  const requestId = mutation.data?.review_request_id ?? data.review.review_request_id;
  const pending = mutation.isSuccess || data.review.state === "pending_review";

  if (pending) {
    return (
      <p data-testid="review-state">
        <strong>{STRINGS.pendingReview}</strong>. {STRINGS.reviewRequestId}:{" "}
        <span data-testid="review-request-id">{orUnknown(requestId)}</span>
      </p>
    );
  }
  return (
    <div>
      <button
        type="button"
        disabled={mutation.isPending}
        onClick={() => mutation.mutate({ domainId, recommendationId: rec.recommendation_id })}
      >
        {mutation.isPending ? STRINGS.routing : STRINGS.routeToReview}
      </button>
      {mutation.isError ? (
        <p role="alert" data-testid="route-error">
          {STRINGS.routeFailed}
          {mutation.error.message !== "" ? `: ${mutation.error.message}` : ""}
        </p>
      ) : null}
    </div>
  );
}

function Detail({
  domainId,
  data,
}: {
  readonly domainId: string;
  readonly data: RecommendationDetailResponse;
}): ReactElement {
  const rec = data.recommendation;
  const S = STRINGS.sections;
  const insufficient = rec.evidence_status === "insufficient_evidence";
  return (
    <article aria-label={STRINGS.detailTitle}>
      <h1>{KIND_LABELS[rec.kind]}</h1>
      <div>
        <AdvisoryBadge advisory={rec.advisory} executable={data.execution.executable} />{" "}
        <EvidenceStatus rec={rec} />
      </div>
      {rec.kind === "candidate_duplicate" ? (
        <p data-testid="duplicate-note">{STRINGS.duplicateNote}</p>
      ) : null}
      {insufficient ? (
        <p data-testid="insufficient-history">{STRINGS.insufficientHistory}</p>
      ) : (
        <>
          <h2>{S.score}</h2>
          <p data-testid="score">{orUnknown(rec.score)}</p>
        </>
      )}
      <h2>{S.subjects}</h2>
      <ul>
        {rec.subject_ids.map((id) => (
          <li key={id}>{id}</li>
        ))}
      </ul>
      <h2>{S.evidenceWindow}</h2>
      <p data-testid="evidence-window">
        {orUnknown(rec.evidence_window?.start)} to {orUnknown(rec.evidence_window?.end)}
      </p>
      <h2>{S.coverage}</h2>
      <p data-testid="coverage">{coverageText(rec.coverage)}</p>
      <h2>{S.uncertainty}</h2>
      <p data-testid="uncertainty">{uncertaintyText(rec.uncertainty)}</p>
      <h2>{S.prerequisites}</h2>
      {rec.prerequisites.length === 0 ? (
        <p data-testid="prerequisites-empty">{STRINGS.unknown}</p>
      ) : (
        <ul data-testid="prerequisites">
          {rec.prerequisites.map((p) => (
            <li key={p.kind}>
              {p.kind}: {orUnknown(p.status)}
            </li>
          ))}
        </ul>
      )}
      <h2>{S.estimate}</h2>
      <EstimateBlock estimate={rec.projected_estimate} />
      <h2>{S.owner}</h2>
      <p data-testid="owner">{ownerText(rec.owner)}</p>
      <h2>{S.generator}</h2>
      <p data-testid="generator">
        {rec.generator === undefined
          ? STRINGS.unknown
          : `${orUnknown(rec.generator.generator_id)} ${orUnknown(rec.generator.generator_version)}`}
      </p>
      <h2>{S.evidenceIds}</h2>
      {rec.evidence_ids.length === 0 ? (
        <p data-testid="evidence-ids-empty">{STRINGS.unknown}</p>
      ) : (
        <ul data-testid="evidence-ids">
          {rec.evidence_ids.map((id) => (
            <li key={id}>{id}</li>
          ))}
        </ul>
      )}
      <ReviewControl domainId={domainId} data={data} />
    </article>
  );
}

export function RecommendationDetailPage(): ReactElement {
  const [params] = useSearchParams();
  const domainId = params.get("domain_id") ?? "";
  const recommendationId = params.get("recommendation_id") ?? "";
  const ready = domainId !== "" && recommendationId !== "";
  const query = useRecommendation({ domainId, recommendationId }, ready);
  const back = `/recommendations?${new URLSearchParams({ domain_id: domainId }).toString()}`;

  return (
    <section aria-label={STRINGS.detailTitle}>
      <p>
        <Link to={back}>{STRINGS.back}</Link>
      </p>
      {!ready ? (
        <p data-testid="domain-required">{STRINGS.domainRequired}</p>
      ) : query.isError ? (
        <QueryErrorState error={query.error} />
      ) : query.isPending ? (
        <p aria-busy="true">{STRINGS.loading}</p>
      ) : (
        <Detail domainId={domainId} data={query.data} />
      )}
    </section>
  );
}
