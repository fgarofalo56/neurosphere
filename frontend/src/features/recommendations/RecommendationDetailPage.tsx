import { Button } from "@fluentui/react-components";
import type { ReactElement } from "react";
import { Link, useSearchParams } from "react-router";
import { useSelectedDomain } from "../../app/domain";
import {
  EmptyState,
  KpiCard,
  LoadingState,
  PageTemplate,
  Panel,
  Timestamp,
} from "../../design-system";
import {
  AdvisoryBadge,
  EstimateBlock,
  EvidenceStatus,
  QueryErrorState,
  confidenceText,
  coverageText,
  impactText,
  ownerText,
  uncertaintyText,
} from "./components";
import { useRecommendation, useRouteToReview } from "./hooks";
import { KIND_LABELS, STRINGS, orUnknown } from "./strings";
import type { Recommendation, RecommendationDetailResponse } from "./types";

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
      <Button
        disabled={mutation.isPending}
        onClick={() => mutation.mutate({ domainId, recommendationId: rec.recommendation_id })}
      >
        {mutation.isPending ? STRINGS.routing : STRINGS.routeToReview}
      </Button>
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
    <>
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
        <Panel landmark="region" title={S.score}>
          <p data-testid="score">{orUnknown(rec.score)}</p>
        </Panel>
      )}
      <Panel landmark="region" title={S.subjects}>
        <ul>
          {rec.subject_ids.map((id) => (
            <li key={id}>{id}</li>
          ))}
        </ul>
      </Panel>
      <Panel landmark="region" title={S.evidenceWindow}>
        <p data-testid="evidence-window">
          <Timestamp value={rec.evidence_window?.start} /> to{" "}
          <Timestamp value={rec.evidence_window?.end} />
        </p>
      </Panel>
      <Panel landmark="region" title={S.coverage}>
        <p data-testid="coverage">{coverageText(rec.coverage)}</p>
      </Panel>
      <Panel landmark="region" title={S.uncertainty}>
        <p data-testid="uncertainty">{uncertaintyText(rec.uncertainty)}</p>
      </Panel>
      <Panel landmark="region" title={S.prerequisites}>
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
      </Panel>
      <Panel landmark="region" title={S.estimate}>
        <EstimateBlock estimate={rec.projected_estimate} />
      </Panel>
      <Panel landmark="region" title={S.owner}>
        <p data-testid="owner">{ownerText(rec.owner)}</p>
      </Panel>
      <Panel landmark="region" title={S.generator}>
        <p data-testid="generator">
          {rec.generator == null
            ? STRINGS.unknown
            : `${orUnknown(rec.generator.generator_id)} ${orUnknown(rec.generator.generator_version)}`}
        </p>
      </Panel>
      <Panel landmark="region" title={S.evidenceIds}>
        {rec.evidence_ids.length === 0 ? (
          <p data-testid="evidence-ids-empty">{STRINGS.unknown}</p>
        ) : (
          <ul data-testid="evidence-ids">
            {rec.evidence_ids.map((id) => (
              <li key={id}>{id}</li>
            ))}
          </ul>
        )}
      </Panel>
      <ReviewControl domainId={domainId} data={data} />
    </>
  );
}

function DetailKpis({ rec }: { readonly rec: Recommendation }): ReactElement {
  return (
    <>
      <KpiCard label="Projected change" value={impactText(rec.projected_estimate)} />
      <KpiCard label="Confidence" value={confidenceText(rec)} />
      <KpiCard label={STRINGS.sections.score} value={orUnknown(rec.score)} />
    </>
  );
}

export function RecommendationDetailPage(): ReactElement {
  const [params] = useSearchParams();
  const { domainId } = useSelectedDomain();
  const recommendationId = params.get("recommendation_id") ?? "";
  const ready = domainId !== "" && recommendationId !== "";
  const query = useRecommendation({ domainId, recommendationId }, ready);
  const back = `/recommendations?${new URLSearchParams({ domain_id: domainId }).toString()}`;
  const title =
    ready && query.isSuccess ? KIND_LABELS[query.data.recommendation.kind] : STRINGS.detailTitle;

  return (
    <PageTemplate
      title={title}
      busy={ready && query.isPending}
      description={<Link to={back}>{STRINGS.back}</Link>}
      kpis={ready && query.isSuccess ? <DetailKpis rec={query.data.recommendation} /> : undefined}
    >
      {!ready ? (
        <div data-testid="domain-required">
          <EmptyState title={STRINGS.domainRequired} />
        </div>
      ) : query.isError ? (
        <QueryErrorState error={query.error} />
      ) : query.isPending ? (
        <div aria-busy="true">
          <LoadingState label={STRINGS.loading} />
        </div>
      ) : (
        <Detail domainId={domainId} data={query.data} />
      )}
    </PageTemplate>
  );
}
