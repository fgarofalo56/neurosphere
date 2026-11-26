"""Governance policy route logic (PRP-105 item 6, acceptance criteria 4, 5, 8 and 10).

Scope rule (criterion 8): every route names its domain in the path and the route dependency
checks the caller's SERVER-DERIVED scope there (``govpolicy.read`` for reads, ``govpolicy.manage``
for drafts and publish intents, ``action.propose`` for an exception request). A record is then
served only when it belongs to that domain, the caller's cloud and customer; anything else is
404 ``not_found``, the same answer as a missing id. Customer-wide policies live in the customer
control domain (``customer_control_domain_id``), so they need the permission there.

Writes:

* ``POST .../policies`` and ``PUT .../draft`` validate the draft (closed rule kinds, per-kind
  parameter models, no free-text condition; 422 ``invalid_schema`` and nothing stored), then
  write it under a ``govpolicy.draft_create`` / ``govpolicy.draft_replace`` before/after audit
  pair on the customer's governance-policy chain (fail closed: no audit, no write);
* ``POST .../publish`` and ``.../retire`` never write the policy. They run the publish dry run
  (``enforce_requires_mode_change``, ``rule_kind_unavailable``; 422) and DRAFT a
  ``governance_policy_publish`` intent through the one action plane (``ActionApi.draft``, the
  same call as REST, chat and MCP) with the item-3 diff, which binds the exact version by
  ``test /policy_version`` and ``test /policy_digest``. Until PRP-108 registers the
  platform-control write target the intent is advisory ("no supported write connector" at
  validation) and the version stays a draft;
* ``POST .../exception-requests`` goes through :class:`ExceptionRequester` (audited
  ``govpolicy.exception_request``; the requester is the HITL maker, so it cannot review it).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from datetime import UTC, datetime
from typing import Any, Final

from neurosphere_contracts.actions.v1.target_ref import TargetRef as ActionTargetRef
from neurosphere_core.audit import AuditContext, build_after, build_before, run_audited_mutation
from neurosphere_core.audit.builders import make_subject
from neurosphere_core.auth.scope import Permission, domains_with_permission
from neurosphere_core.errors import NeuroSphereError
from neurosphere_core.governance.policy import (
    ENFORCEMENT_POINT_CAPABILITIES,
    GOVERNANCE_POLICY_PUBLISH_KIND,
    POLICY_SCHEMA_VERSION,
    RULE_KINDS,
    ExceptionFilters,
    ExceptionRequest,
    GovernancePolicyNotFoundError,
    GovernancePolicyStaleError,
    PolicyPublishedError,
    PublishStage,
    StoredBinding,
    StoredException,
    StoredPolicy,
    StoredViolation,
    ViolationFilters,
    governance_policy_canonical_id,
    governance_policy_chain_id,
    policy_digest,
    publish_diff,
    publish_refusals,
    publish_target,
    publish_target_version,
    validate_draft,
)
from neurosphere_core.governance.policy.ids import GOVERNANCE_POLICY_ENTITY_TYPE
from neurosphere_core.governance.policy.store import (
    POLICY_DRAFT_EXISTS,
    POLICY_EXISTS,
    POLICY_NOT_FOUND,
    POLICY_RETIRED,
    VIOLATION_NOT_FOUND,
)
from neurosphere_core.paging import PageRequest
from neurosphere_core.scope import IdentityScope

from neurosphere_api.actions.dependencies import ActionPlane
from neurosphere_api.actions.models import ActionView, DraftIntentBody
from neurosphere_api.actions.service import ActionApi
from neurosphere_api.governance.policy.deps import GovernancePolicyPlane
from neurosphere_api.governance.policy.models import (
    BindingList,
    BindingView,
    ExceptionList,
    ExceptionRequestBody,
    ExceptionRequestView,
    ExceptionView,
    GovernanceStatusView,
    PointCapabilityView,
    PolicyCreateBody,
    PolicyDraftBody,
    PolicyList,
    PolicyStageBody,
    PolicyView,
    PublishRefusalView,
    RuleKindStatusView,
    RunStatusView,
    VersionList,
    ViolationList,
    ViolationView,
)

__all__ = [
    "ANNOUNCED_RULE_KINDS",
    "MAX_STATUS_DOMAINS",
    "OPERATION_DRAFT_CREATE",
    "OPERATION_DRAFT_REPLACE",
    "GovernancePolicyService",
    "point_capabilities",
    "principal_id_of",
]

OPERATION_DRAFT_CREATE: Final = "govpolicy.draft_create"
OPERATION_DRAFT_REPLACE: Final = "govpolicy.draft_replace"
#: At most this many domains get a run-status read per ``GET /status`` (bounded; the view says
#: ``runs_truncated`` when the caller can read more).
MAX_STATUS_DOMAINS: Final = 50
#: Rule kinds announced by later PRPs that are not yet in the PRP-99 closed list
#: (``identity_entitlement``: PRP-110 adds the kind, PRP-119 its evaluator). ``GET /status``
#: reports them ``evaluator_unavailable`` so nobody mistakes them for evaluated.
ANNOUNCED_RULE_KINDS: Final = ("identity_entitlement",)


def _timestamp(moment: datetime) -> str:
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def principal_id_of(scope: IdentityScope) -> str:
    principal = scope.to_contract().principal.principal_id
    return str(getattr(principal, "root", principal))


def _reason(exc: BaseException) -> str:
    reason = getattr(exc, "reason", None) if isinstance(exc, NeuroSphereError) else None
    return reason if isinstance(reason, str) and reason else "error"


def _in_domain(record_cloud: str, record_domain: str, scope: IdentityScope, domain: str) -> bool:
    return record_cloud == scope.cloud and record_domain == domain


def point_capabilities() -> list[PointCapabilityView]:
    """The fixed point capability table, in point order."""
    return [
        PointCapabilityView(
            point=point,
            can_block=capability.can_block,
            what_it_blocks=capability.what_it_blocks,
            owning_prp=capability.owning_prp,
        )
        for point, capability in ENFORCEMENT_POINT_CAPABILITIES.items()
    ]


class GovernancePolicyService:
    """One request's view of the plane (see the module docstring for the rules)."""

    def __init__(self, plane: GovernancePolicyPlane) -> None:
        self._plane = plane

    # -- views -------------------------------------------------------------------------------

    def policy_view(self, stored: StoredPolicy) -> PolicyView:
        policy = stored.policy
        refusals = (
            publish_refusals(policy, self._plane.registry) if policy.status == "draft" else ()
        )
        return PolicyView(
            policy=policy.model_dump(mode="json"),
            etag=stored.etag,
            policy_digest=policy_digest(policy),
            publish_refusals=[
                PublishRefusalView(reason=r.reason, pointer=r.pointer) for r in refusals
            ],
        )

    @staticmethod
    def violation_view(stored: StoredViolation) -> ViolationView:
        return ViolationView(violation=stored.violation.model_dump(mode="json"), etag=stored.etag)

    @staticmethod
    def exception_view(stored: StoredException) -> ExceptionView:
        return ExceptionView(exception=stored.exception.model_dump(mode="json"), etag=stored.etag)

    @staticmethod
    def binding_view(stored: StoredBinding) -> BindingView:
        binding = stored.binding
        capability = ENFORCEMENT_POINT_CAPABILITIES.get(binding.point.root)
        return BindingView(
            binding=binding.model_dump(mode="json"),
            etag=stored.etag,
            version=stored.version,
            retired=stored.retired,
            capability=None
            if capability is None
            else PointCapabilityView(
                point=binding.point.root,
                can_block=capability.can_block,
                what_it_blocks=capability.what_it_blocks,
                owning_prp=capability.owning_prp,
            ),
        )

    # -- policies ----------------------------------------------------------------------------

    async def list_policies(
        self, scope: IdentityScope, domain: str, *, cursor: str | None, limit: int
    ) -> PolicyList:
        page = await self._plane.policies.list(
            scope.customer_id, (domain,), PageRequest(page_size=limit, cursor=cursor)
        )
        items = [
            self.policy_view(s)
            for s in page.items
            if _in_domain(s.policy.cloud.root, s.policy.domain_id.root, scope, domain)
        ]
        return PolicyList(items=items, next_cursor=page.next_cursor)

    async def get_policy(
        self, scope: IdentityScope, domain: str, policy_id: str, *, version: int | None = None
    ) -> StoredPolicy:
        stored = await self._plane.policies.get(scope.customer_id, policy_id, version=version)
        if stored is None or not _in_domain(
            stored.policy.cloud.root, stored.policy.domain_id.root, scope, domain
        ):
            raise GovernancePolicyNotFoundError(POLICY_NOT_FOUND)
        return stored

    async def versions(self, scope: IdentityScope, domain: str, policy_id: str) -> VersionList:
        await self.get_policy(scope, domain, policy_id)  # 404 unless the policy is in the domain
        stored = await self._plane.policies.versions(scope.customer_id, policy_id)
        return VersionList(
            items=[
                self.policy_view(s)
                for s in stored
                if _in_domain(s.policy.cloud.root, s.policy.domain_id.root, scope, domain)
            ]
        )

    def draft_document(
        self,
        scope: IdentityScope,
        domain: str,
        policy_id: str,
        body: PolicyDraftBody,
        *,
        version: int,
        previous: int | None,
        created_by: str,
        created_at: str,
    ) -> dict[str, Any]:
        return {
            "schema_version": POLICY_SCHEMA_VERSION,
            "policy_id": policy_id,
            "policy_version": version,
            "previous_version": previous,
            "cloud": scope.cloud,
            "customer_id": scope.customer_id,
            "domain_id": domain,
            "display_name": body.display_name,
            "document_url": body.document_url,
            "status": "draft",
            "mode": body.mode,
            "severity": body.severity,
            "rules": body.rules,
            "created_by": created_by,
            "created_at": created_at,
            "published_at": None,
            "published_intent_id": None,
            "published_audit_id": None,
        }

    async def _audited_write(
        self,
        scope: IdentityScope,
        correlation_id: str,
        operation: str,
        policy_id: str,
        version: int,
        digest: str,
        write: Callable[[], Awaitable[StoredPolicy]],
    ) -> StoredPolicy:
        ctx = AuditContext.from_scope(
            scope, correlation_id=correlation_id, operation=operation, channel="rest"
        )
        subject = make_subject(
            governance_policy_canonical_id(scope.cloud, scope.customer_id, policy_id),
            GOVERNANCE_POLICY_ENTITY_TYPE,
            target_version=f"v{version}",
            state_digest=digest,
        )
        detail = "draft_created" if operation == OPERATION_DRAFT_CREATE else "draft_replaced"

        return await run_audited_mutation(
            self._plane.audit,
            governance_policy_chain_id(scope.customer_id),
            before=build_before(ctx, subject),
            mutate=write,
            after=lambda _stored: build_after(
                ctx, subject, result="succeeded", verified=True, detail=detail
            ),
            on_error=lambda exc: build_after(
                ctx, subject, result="failed", verified=False, detail=_reason(exc)
            ),
        )

    async def create_draft(
        self, scope: IdentityScope, domain: str, body: PolicyCreateBody, correlation_id: str
    ) -> StoredPolicy:
        """A new policy at version 1, or the next draft after a published or retired version."""
        latest = await self._plane.policies.get(scope.customer_id, body.policy_id)
        version, previous = 1, None
        if latest is not None:
            current = latest.policy
            if not _in_domain(current.cloud.root, current.domain_id.root, scope, domain):
                # Policy ids are unique per customer: the id is taken (409, nothing about where).
                raise GovernancePolicyStaleError(POLICY_EXISTS, "policy id is already used")
            if current.status == "draft":
                raise GovernancePolicyStaleError(
                    POLICY_DRAFT_EXISTS, "the policy already has an open draft"
                )
            version, previous = current.policy_version + 1, current.policy_version
        draft = validate_draft(
            self.draft_document(
                scope,
                domain,
                body.policy_id,
                body,
                version=version,
                previous=previous,
                created_by=principal_id_of(scope),
                created_at=_timestamp(self._plane.clock()),
            )
        )

        async def write() -> StoredPolicy:
            return await self._plane.policies.create_draft(draft)

        return await self._audited_write(
            scope,
            correlation_id,
            OPERATION_DRAFT_CREATE,
            body.policy_id,
            version,
            policy_digest(draft),
            write,
        )

    async def replace_draft(
        self,
        scope: IdentityScope,
        domain: str,
        policy_id: str,
        body: PolicyDraftBody,
        *,
        if_match: str,
        correlation_id: str,
    ) -> StoredPolicy:
        """Replace the open draft under ``If-Match``; a published version is immutable."""
        latest = await self.get_policy(scope, domain, policy_id)
        current = latest.policy
        if current.status == "published":
            raise PolicyPublishedError()
        if current.status != "draft":
            raise GovernancePolicyStaleError(POLICY_RETIRED, "the policy has no open draft")
        draft = validate_draft(
            self.draft_document(
                scope,
                domain,
                policy_id,
                body,
                version=current.policy_version,
                previous=current.previous_version,
                created_by=current.created_by.root,
                created_at=current.created_at.root,
            )
        )

        async def write() -> StoredPolicy:
            return await self._plane.policies.replace_draft(draft, if_match=if_match)

        return await self._audited_write(
            scope,
            correlation_id,
            OPERATION_DRAFT_REPLACE,
            policy_id,
            current.policy_version,
            policy_digest(draft),
            write,
        )

    async def draft_stage_intent(
        self,
        actions: ActionPlane,
        scope: IdentityScope,
        domain: str,
        policy_id: str,
        stage: PublishStage,
        body: PolicyStageBody,
        correlation_id: str,
    ) -> tuple[ActionView, bool]:
        """Dry run, then DRAFT the ``governance_policy_publish`` intent (never a direct write)."""
        stored = await self.get_policy(scope, domain, policy_id, version=body.version)
        policy = stored.policy
        if stage == "publish":
            self._plane.lifecycle.check_publishable(policy)
        diff = publish_diff(stage, policy)
        target = ActionTargetRef.model_validate(publish_target(policy).model_dump(mode="json"))
        draft = DraftIntentBody(
            action_kind=GOVERNANCE_POLICY_PUBLISH_KIND,
            target=target,
            target_version=publish_target_version(policy),
            proposed_diff=diff,
            idempotency_key=body.idempotency_key,
            channel=body.channel,
        )
        return await ActionApi(actions).draft(scope, domain, draft, correlation_id)

    # -- violations and exceptions -----------------------------------------------------------

    async def list_violations(
        self,
        scope: IdentityScope,
        domain: str,
        filters: ViolationFilters,
        *,
        cursor: str | None,
        limit: int,
    ) -> ViolationList:
        page = await self._plane.violations.list(
            scope.customer_id, filters, PageRequest(page_size=limit, cursor=cursor)
        )
        items = [
            self.violation_view(s)
            for s in page.items
            if _in_domain(s.violation.cloud.root, s.violation.domain_id.root, scope, domain)
        ]
        return ViolationList(items=items, next_cursor=page.next_cursor)

    async def get_violation(
        self, scope: IdentityScope, domain: str, violation_id: str
    ) -> StoredViolation:
        stored = await self._plane.violations.get(scope.customer_id, domain, violation_id)
        if stored is None or not _in_domain(
            stored.violation.cloud.root, stored.violation.domain_id.root, scope, domain
        ):
            raise GovernancePolicyNotFoundError(VIOLATION_NOT_FOUND)
        return stored

    async def request_exception(
        self,
        scope: IdentityScope,
        domain: str,
        violation_id: str,
        body: ExceptionRequestBody,
        *,
        correlation_id: str,
    ) -> ExceptionRequestView:
        await self.get_violation(scope, domain, violation_id)  # 404 unless in this domain
        result = await self._plane.exception_requester.request(
            scope,
            ExceptionRequest(
                domain_id=domain,
                violation_id=violation_id,
                justification_code=body.justification_code,
                justification_text=body.justification_text,
                expires_at=body.expires_at,
            ),
            correlation_id=correlation_id,
            channel="rest",
        )
        return ExceptionRequestView(
            exception=result.exception.exception.model_dump(mode="json"),
            etag=result.exception.etag,
            review_item_id=str(result.review_item.item_id),
        )

    async def list_exceptions(
        self,
        scope: IdentityScope,
        domain: str,
        filters: ExceptionFilters,
        *,
        cursor: str | None,
        limit: int,
    ) -> ExceptionList:
        page = await self._plane.exceptions.list(
            scope.customer_id, filters, PageRequest(page_size=limit, cursor=cursor)
        )
        items = [
            self.exception_view(s)
            for s in page.items
            if _in_domain(s.exception.cloud.root, s.exception.domain_id.root, scope, domain)
        ]
        return ExceptionList(items=items, next_cursor=page.next_cursor)

    # -- bindings and status -----------------------------------------------------------------

    async def list_bindings(
        self,
        scope: IdentityScope,
        domain: str,
        *,
        policy_id: str | None,
        point: str | None,
    ) -> BindingList:
        stored = await self._plane.bindings.list(
            scope.customer_id, point=point, policy_id=policy_id, domain_ids=(domain,)
        )
        items = [
            self.binding_view(s)
            for s in stored
            if _in_domain(s.binding.cloud.root, s.binding.domain_id.root, scope, domain)
        ]
        return BindingList(items=items)

    def rule_kind_statuses(self) -> list[RuleKindStatusView]:
        """Every contract kind, every announced kind and anything a plugin registered or
        reported, in that order without repeats."""
        registry = self._plane.registry
        kinds = dict.fromkeys(
            (
                *RULE_KINDS,
                *ANNOUNCED_RULE_KINDS,
                *registry.available_kinds,
                *(u.kind for u in registry.unavailable_kinds),
            )
        )
        return [
            RuleKindStatusView(
                kind=kind, status=registry.status(kind), reason=registry.unavailable_reason(kind)
            )
            for kind in kinds
        ]

    def readable_domains(self, scope: IdentityScope) -> tuple[Sequence[str], bool]:
        """The domains the caller holds ``govpolicy.read`` in (bounded) and whether it was cut."""
        domains = sorted(
            domains_with_permission(scope, Permission.GOVPOLICY_READ, now=self._plane.clock())
        )
        return domains[:MAX_STATUS_DOMAINS], len(domains) > MAX_STATUS_DOMAINS

    async def status(self, scope: IdentityScope) -> GovernanceStatusView:
        domains, truncated = self.readable_domains(scope)
        runs: list[RunStatusView] = []
        for domain in domains:
            latest = await self._plane.statuses.latest(scope.customer_id, domain)
            runs.append(
                RunStatusView(
                    domain_id=domain,
                    status=None if latest is None else latest.status.model_dump(mode="json"),
                )
            )
        return GovernanceStatusView(
            rule_kinds=self.rule_kind_statuses(),
            runs=runs,
            runs_truncated=truncated,
            points=point_capabilities(),
        )
