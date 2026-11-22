"""Agent alias declaration service (PRP-137 item 5).

The plane is installed on ``app.state.agent_identity`` by the ``agent_identity`` builder. Order of
checks for a write: the route's ``require(catalog.curate)`` on the path domain, then the target
(an agent of the caller's cloud and customer that exists in the caller's scope AND lives in the
path domain; anything else is the SAME 404 ``alias_target_not_found``, so a target in another
domain or out of scope cannot be told from a missing one), then the audited write.

Audit records carry ids and reason codes only. The external agent id is never written to an audit
record (it can be a GUID and it is telemetry content); the target and alias ids are.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Final

from fastapi import FastAPI, Request
from neurosphere_core.agent_identity import (
    DeclaredAlias,
    agent_alias_key,
    declare_agent_alias,
    is_owned_agent,
)
from neurosphere_core.audit import (
    AuditContext,
    AuditDraft,
    AuditRepository,
    build_after,
    build_before,
    domain_audit_chain_id,
    make_subject,
    run_audited_mutation,
)
from neurosphere_core.catalog.protocol import CatalogRepository
from neurosphere_core.errors import (
    DependencyTransientError,
    ForbiddenError,
    NeuroSphereError,
    NotFoundError,
)
from neurosphere_core.scope import IdentityScope

from neurosphere_api.agent_identity.models import (
    RERESOLVE_COMMAND,
    AliasDeclareRequest,
    AliasDeclareView,
    AliasView,
    ReresolveJob,
)

__all__ = [
    "OP_DECLARE",
    "OP_RETIRE",
    "STATE_ATTRIBUTE",
    "AgentIdentityPlane",
    "AgentIdentityService",
    "configure_agent_identity",
    "get_plane",
]

STATE_ATTRIBUTE: Final = "agent_identity"
OP_DECLARE: Final = "agent_identity.alias_declare"
OP_RETIRE: Final = "agent_identity.alias_retire"
_UNCONFIGURED: Final = "agent_identity_unconfigured"
_TARGET_MISSING: Final = "alias_target_not_found"
_ALIAS_MISSING: Final = "alias_not_found"

Clock = Callable[[], datetime]


@dataclass(frozen=True)
class AgentIdentityPlane:
    """What the routes need: the catalog repository (the one the catalog routes use)."""

    repository: CatalogRepository


def configure_agent_identity(app: FastAPI, plane: AgentIdentityPlane | None) -> None:
    setattr(app.state, STATE_ATTRIBUTE, plane)


def get_plane(request: Request) -> AgentIdentityPlane:
    plane = getattr(request.app.state, STATE_ATTRIBUTE, None)
    if not isinstance(plane, AgentIdentityPlane):
        raise DependencyTransientError("agent identity is not configured", reason=_UNCONFIGURED)
    return plane


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _missing(reason: str) -> NotFoundError:
    return NotFoundError("the agent was not found", reason=reason)


def _refusal(exc: BaseException) -> str:
    if isinstance(exc, NeuroSphereError):
        reason = getattr(exc, "reason", None)
        return reason if isinstance(reason, str) and reason else exc.code
    return "error"


def _job(scope: IdentityScope, body: AliasDeclareRequest) -> ReresolveJob:
    return ReresolveJob(
        command=RERESOLVE_COMMAND,
        arguments=[
            "--customer",
            scope.customer_id,
            "--source-id",
            body.source_id,
            "--external-agent-id",
            body.external_agent_id,
        ],
    )


class AgentIdentityService:
    def __init__(
        self, repository: CatalogRepository, audit: AuditRepository, clock: Clock | None = None
    ) -> None:
        self._repo = repository
        self._audit = audit
        self._clock = clock or _utc_now

    async def _require_target(self, scope: IdentityScope, domain: str, target: str) -> None:
        """The target is an owned agent, visible to the caller and in ``domain``; else one 404."""
        if not is_owned_agent(target, scope.cloud, scope.customer_id):
            raise _missing(_TARGET_MISSING)
        try:
            entity = await self._repo.get_entity(scope, target)
        except ForbiddenError:
            raise _missing(_TARGET_MISSING) from None
        held = getattr(entity, "domain_id", None)
        if entity is None or getattr(held, "root", held) != domain:
            raise _missing(_TARGET_MISSING)

    async def declare(
        self,
        scope: IdentityScope,
        domain: str,
        body: AliasDeclareRequest,
        *,
        correlation_id: str,
    ) -> AliasDeclareView:
        await self._require_target(scope, domain, body.target_agent_id)
        ctx = AuditContext.from_scope(
            scope, correlation_id=correlation_id, operation=OP_DECLARE, channel="rest"
        )
        chain = domain_audit_chain_id(scope.customer_id, domain)
        subject = make_subject(body.target_agent_id, "agent")
        code = "declared" if body.reason is None else f"declared:reason={body.reason}"

        async def mutate() -> DeclaredAlias:
            try:
                return await declare_agent_alias(
                    self._repo,
                    scope,
                    source_id=body.source_id,
                    external_agent_id=body.external_agent_id,
                    target_agent_id=body.target_agent_id,
                    clock=self._clock,
                )
            except ForbiddenError:
                raise _missing(_TARGET_MISSING) from None

        def succeeded(result: DeclaredAlias) -> AuditDraft:
            return build_after(
                ctx,
                make_subject(result.alias_id or body.target_agent_id, "alias"),
                result="succeeded",
                verified=True,
                detail=f"{result.outcome}:{code}",
            )

        def failed(exc: BaseException) -> AuditDraft:
            return build_after(ctx, subject, result="failed", verified=False, detail=_refusal(exc))

        declared = await run_audited_mutation(
            self._audit,
            chain,
            before=build_before(ctx, subject),
            mutate=mutate,
            after=succeeded,
            on_error=failed,
        )
        if declared.retired_alias_id is not None:
            retire_ctx = AuditContext.from_scope(
                scope, correlation_id=correlation_id, operation=OP_RETIRE, channel="rest"
            )
            await self._audit.append(
                chain,
                build_after(
                    retire_ctx,
                    make_subject(declared.retired_alias_id, "alias"),
                    result="succeeded",
                    verified=True,
                    detail="retired:repointed",
                ),
            )
        needed = declared.outcome != "unchanged"
        return AliasDeclareView(
            outcome=declared.outcome,
            alias_id=declared.alias_id,
            retired_alias_id=declared.retired_alias_id,
            target_agent_id=body.target_agent_id,
            reresolve_needed=needed,
            reresolve_job=_job(scope, body) if needed else None,
        )

    async def lookup(
        self, scope: IdentityScope, domain: str, source_id: str, external_agent_id: str
    ) -> AliasView:
        """The active alias target, or the same 404 for none, out of scope or another domain."""
        try:
            target = await self._repo.resolve_alias(
                scope, agent_alias_key(source_id, external_agent_id)
            )
        except ForbiddenError:
            raise _missing(_ALIAS_MISSING) from None
        if target is None:
            raise _missing(_ALIAS_MISSING)
        try:
            await self._require_target(scope, domain, target)
        except NotFoundError:
            raise _missing(_ALIAS_MISSING) from None
        return AliasView(
            source_id=source_id, external_agent_id=external_agent_id, target_agent_id=target
        )
