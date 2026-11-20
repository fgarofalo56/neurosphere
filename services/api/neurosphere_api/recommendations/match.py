"""Agent and tool match routes (PRP-72 item 4).

Mounted at ``/api/v1/recommendations/domains/{domain}/match`` (a second recommendations prefix, so
``router.py`` stays untouched):

| Method | Path                                                 | Permission  | Status |
|--------|------------------------------------------------------|-------------|--------|
| POST   | ``/domains/{domain}/match``                          | ``data.read`` | 200  |
| POST   | ``/domains/{domain}/match/feedback``                 | ``data.read`` | 202  |
| GET    | ``/domains/{domain}/match/metrics``                  | ``data.read`` | 200  |

A match is advisory: nothing is invoked or changed. The path ``{domain}`` is the addressed
resource and the authorization TARGET (403 with a denial record outside the caller's scope);
cloud, customer and every other scope field come from the derived ``IdentityScope``. Candidates
are drawn from every domain in the caller's scope (see PRP-72 clarification 4); context entity
ids outside that scope are refused with 403 ``context_entity_out_of_scope``, never ignored.

A feedback decision is a small write, so it goes through ``run_audited_mutation`` (before and
after records, fail closed). Task text is tokenized by the matcher and is never logged, audited or
returned by this module; the audit state holds only ids and the decision.

No ``from __future__ import annotations``: FastAPI inspects these signatures.
"""

from datetime import UTC, datetime, timedelta
from typing import Annotated, Any, Final

from fastapi import APIRouter, Depends, Path, Query, Request
from neurosphere_core.audit import (
    AuditContext,
    AuditDraft,
    AuditRepository,
    build_after,
    build_before,
    make_subject,
    run_audited_mutation,
)
from neurosphere_core.audit.chains import domain_audit_chain_id
from neurosphere_core.auth.scope import Permission
from neurosphere_core.errors import InvalidSchemaError, NeuroSphereError
from neurosphere_core.recommendations.matching import AgentMatcher
from neurosphere_core.scope import IdentityScope

from neurosphere_api.actions.common import audit_correlation_id
from neurosphere_api.authz import domain_from_path, require
from neurosphere_api.middleware import correlation_id_of
from neurosphere_api.recommendations.match_dependencies import get_agent_matcher, get_match_audit
from neurosphere_api.recommendations.match_models import (
    AgentMatchFeedbackRequest,
    AgentMatchRequest,
    AgentMatchView,
    CandidateAssessment,
    FeedbackAccepted,
    MatchMetricsView,
)
from neurosphere_api.routers import RouterRegistry

__all__ = ["PREFIX", "build_router", "register"]

PREFIX: Final = "/api/v1/recommendations/domains/{domain}/match"

DEFAULT_WINDOW: Final = timedelta(days=30)
MAX_WINDOW: Final = timedelta(days=366)
_FEEDBACK_OPERATION: Final = "recommendations.match.feedback"

ReadScope = Annotated[
    IdentityScope, Depends(require(Permission.DATA_READ, domain_from_path("domain")))
]
Matcher = Annotated[AgentMatcher, Depends(get_agent_matcher)]
Audit = Annotated[AuditRepository, Depends(get_match_audit)]
DomainPath = Annotated[str, Path(min_length=1, max_length=512)]


def _plain(value: Any) -> str:
    """Plain string of a contract scalar (RootModel wrappers expose ``root``, sometimes nested)."""
    while hasattr(value, "root"):
        value = value.root
    return str(value)


def _aware(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _refusal(exc: BaseException) -> str:
    if isinstance(exc, NeuroSphereError):
        reason = getattr(exc, "reason", None)
        return reason if isinstance(reason, str) and reason else exc.code
    return "error"


def _entity_type(entity_id: str) -> str:
    parts = entity_id.split(":")
    return parts[3] if len(parts) == 5 else "agent"


def build_router() -> APIRouter:
    router = APIRouter(tags=["recommendations"])

    @router.post("", response_model=AgentMatchView, status_code=200)
    async def match_agents(
        domain: DomainPath, body: AgentMatchRequest, scope: ReadScope, matcher: Matcher
    ) -> AgentMatchView:
        result = await matcher.match_detailed(scope, domain, body)
        assessments = [
            CandidateAssessment(
                entity_id=_plain(c.entity_id),
                confidence=result.confidence.get(_plain(c.entity_id), 0.0),
                cold_start=result.cold_start.get(_plain(c.entity_id), False),
            )
            for c in result.response.candidates
        ]
        return AgentMatchView(match=result.response, assessments=assessments)

    @router.post("/feedback", response_model=FeedbackAccepted, status_code=202)
    async def record_match_feedback(
        domain: DomainPath,
        body: AgentMatchFeedbackRequest,
        request: Request,
        scope: ReadScope,
        matcher: Matcher,
        audit: Audit,
    ) -> FeedbackAccepted:
        ctx = AuditContext.from_scope(
            scope,
            correlation_id=audit_correlation_id(correlation_id_of(request.scope)),
            operation=_FEEDBACK_OPERATION,
            channel="rest",
        )
        entity_id = _plain(body.entity_id)
        subject = make_subject(
            entity_id,
            _entity_type(entity_id),
            state={
                "match_id": body.match_id,
                "decision": body.decision,
                "reason_code": body.reason_code,
            },
        )

        async def mutate() -> FeedbackAccepted:
            record = await matcher.record_feedback(scope, domain, body)
            return FeedbackAccepted(
                match_id=record.match_id,
                entity_id=record.entity_id,
                decision=record.decision,
                decided_at=record.decided_at,
            )

        def after(result: FeedbackAccepted) -> AuditDraft:
            return build_after(
                ctx,
                subject,
                result="succeeded",
                verified=True,
                detail=f"feedback_{result.decision}",
            )

        def failed(exc: BaseException) -> AuditDraft:
            return build_after(ctx, subject, result="failed", verified=False, detail=_refusal(exc))

        return await run_audited_mutation(
            audit,
            domain_audit_chain_id(scope.customer_id, domain),
            before=build_before(ctx, subject),
            mutate=mutate,
            after=after,
            on_error=failed,
        )

    @router.get("/metrics", response_model=MatchMetricsView)
    async def match_metrics(
        domain: DomainPath,
        scope: ReadScope,
        matcher: Matcher,
        since: Annotated[datetime | None, Query()] = None,
        until: Annotated[datetime | None, Query()] = None,
    ) -> MatchMetricsView:
        end = _aware(until) if until is not None else datetime.now(UTC)
        start = _aware(since) if since is not None else end - DEFAULT_WINDOW
        if start >= end or end - start > MAX_WINDOW:
            raise InvalidSchemaError(
                "the window must be positive and at most 366 days", reason="invalid_window"
            )
        stats = await matcher.metrics(scope, domain, start, end)
        return MatchMetricsView(
            domain_id=domain,
            window_start=start,
            window_end=end,
            matches=stats.matches,
            matches_with_feedback=stats.matches_with_feedback,
            accepts=stats.accepts,
            rejects=stats.rejects,
            acceptance_rate=stats.acceptance_rate,
        )

    return router


def register(registry: RouterRegistry) -> None:
    registry.register(PREFIX, build_router())
