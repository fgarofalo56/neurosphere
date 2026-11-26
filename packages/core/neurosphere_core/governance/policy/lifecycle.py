"""Publish and retire a policy version (PRP-105 item 3, acceptance criteria 5, 6, 9 and 10).

:class:`PolicyLifecycle` is the ONLY code that sets a policy version ``published`` or ``retired``
(through :meth:`~.store.PolicyDefinitionStore.mark_published` / ``mark_retired``). It is what
PRP-108's platform-control handler calls once a ``governance_policy_publish`` intent has been
confirmed and approved, and what the ``NS_ENV=local`` seed loader (item 6) calls with audit
operation ``govpolicy.seed``. No route writes a published state directly.

Publish, in order:

1. read the exact version; it must be in the caller's derived scope (else ``not_found``, the
   same answer as missing), match ``expected_etag`` (and ``expected_digest`` when the intent
   carried one), and still be a draft;
2. :func:`check_publishable` - the dry run the API also calls before drafting: ``mode: enforce``
   is refused ``enforce_requires_mode_change`` (GD-7: ``enforce`` is only ever a per-point
   approved ``enforcement_mode_change``), and any rule kind without an evaluator in this
   deployment is refused ``rule_kind_unavailable`` (criterion 10: no policy looks active while
   doing nothing);
3. ``govpolicy.publish`` ``before`` audit record (fail closed: no audit, no publish); its
   ``audit_id`` is the version's ``published_audit_id``;
4. mark published; then :meth:`~.store.BindingStore.ensure_bindings` at ``audit`` (``off`` when
   the policy's mode is ``off``) for every point :data:`~.models.POINTS_BY_RULE_KIND` allows;
   bindings never start in ``enforce`` and an existing binding keeps its mode;
5. project the catalog ``Policy`` entity; a projection or binding failure leaves the policy
   published and is reported by reason code: :meth:`PolicyLifecycle.reconcile`, which the
   evaluator calls every tick, retries both;
6. ``after`` audit record with the binding count and the projection outcome.

Retire mirrors it with ``govpolicy.retire`` and the catalog entity ``deprecated`` (unless another
version of the policy is still published, which is then projected instead).
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Final, Literal

from neurosphere_contracts.audit.v1.audit_record import Subject

from neurosphere_core.audit import (
    AuditContext,
    AuditRepository,
    build_after,
    build_before,
)
from neurosphere_core.audit.builders import Channel, make_subject
from neurosphere_core.catalog.protocol import CatalogRepository
from neurosphere_core.errors import (
    InvalidSchemaError,
    NeuroSphereError,
    ValidationIssue,
)
from neurosphere_core.governance.policy.actions import policy_digest
from neurosphere_core.governance.policy.ids import (
    GOVERNANCE_POLICY_ENTITY_TYPE,
    governance_policy_canonical_id,
    governance_policy_chain_id,
)
from neurosphere_core.governance.policy.models import (
    POINTS_BY_RULE_KIND,
    EnforcementPointName,
    PolicyDefinition,
)
from neurosphere_core.governance.policy.projection import (
    ProjectionResult,
    deprecate_policy_entity,
    project_policy,
)
from neurosphere_core.governance.policy.rules.registry import RuleEvaluatorRegistry
from neurosphere_core.governance.policy.store import (
    ENFORCE_REQUIRES_MODE_CHANGE,
    POLICY_MODIFIED,
    POLICY_NOT_FOUND,
    POLICY_NOT_PUBLISHED,
    POLICY_RETIRED,
    BindingStore,
    GovernancePolicyNotFoundError,
    GovernancePolicyStaleError,
    PolicyDefinitionStore,
    PolicyPublishedError,
    StoredBinding,
    StoredPolicy,
)
from neurosphere_core.governance.policy.validation import validate_policy
from neurosphere_core.scope import IdentityScope

__all__ = [
    "BINDINGS_FAILED",
    "INTENT_REQUIRED",
    "OPERATION_PUBLISH",
    "OPERATION_RETIRE",
    "OPERATION_SEED",
    "RULE_KIND_UNAVAILABLE",
    "LifecycleAuditContext",
    "LifecycleOutcome",
    "PolicyLifecycle",
    "PublishRefusal",
    "PublishRefusedError",
    "ReconcileOutcome",
    "binding_mode_for",
    "binding_points_for",
    "check_publishable",
    "publish_refusals",
]

OPERATION_PUBLISH: Final = "govpolicy.publish"
OPERATION_RETIRE: Final = "govpolicy.retire"
OPERATION_SEED: Final = "govpolicy.seed"
RULE_KIND_UNAVAILABLE: Final = "rule_kind_unavailable"
BINDINGS_FAILED: Final = "bindings_failed"
INTENT_REQUIRED: Final = "intent_required"

Clock = Callable[[], datetime]

_log = logging.getLogger(__name__)


def _utc_now() -> datetime:
    return datetime.now(UTC)


# --- the dry run ---------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PublishRefusal:
    """One reason a version cannot be published: a reason code and an RFC 6901 pointer."""

    reason: str
    pointer: str


class PublishRefusedError(InvalidSchemaError):
    """The publish dry run refused the version (``invalid_schema``, 422; nothing changed).

    ``reason`` is the first refusal (``enforce_requires_mode_change`` before
    ``rule_kind_unavailable``); ``errors`` lists every one.
    """

    def __init__(self, refusals: tuple[PublishRefusal, ...]) -> None:
        super().__init__(
            "the policy version cannot be published",
            errors=[ValidationIssue(r.pointer, r.reason) for r in refusals],
            reason=refusals[0].reason,
        )
        self.refusals = refusals


def publish_refusals(
    policy: PolicyDefinition, registry: RuleEvaluatorRegistry
) -> tuple[PublishRefusal, ...]:
    """Every reason ``policy`` cannot be published here (empty = publishable)."""
    refusals: list[PublishRefusal] = []
    if policy.mode is not None and policy.mode.root == "enforce":
        refusals.append(PublishRefusal(ENFORCE_REQUIRES_MODE_CHANGE, "/mode"))
    for index, rule in enumerate(policy.rules):
        if rule.kind.root not in registry:
            refusals.append(PublishRefusal(RULE_KIND_UNAVAILABLE, f"/rules/{index}/kind"))
    return tuple(refusals)


def check_publishable(policy: PolicyDefinition, registry: RuleEvaluatorRegistry) -> None:
    """The publish dry run: raises :class:`PublishRefusedError` when :func:`publish_refusals`
    finds anything. The API calls it before drafting a publish intent; publish calls it again."""
    refusals = publish_refusals(policy, registry)
    if refusals:
        raise PublishRefusedError(refusals)


def binding_mode_for(policy: PolicyDefinition) -> Literal["audit", "off"]:
    """The mode bindings start in: ``off`` for an ``off`` policy, otherwise ``audit``."""
    return "off" if policy.mode is not None and policy.mode.root == "off" else "audit"


def binding_points_for(policy: PolicyDefinition) -> tuple[EnforcementPointName, ...]:
    """Every point a rule of ``policy`` can bind to, in rule order, without repeats."""
    points: dict[EnforcementPointName, None] = {}
    for rule in policy.rules:
        for point in POINTS_BY_RULE_KIND.get(rule.kind.root, ()):
            points[point] = None
    return tuple(points)


# --- context and outcomes -----------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class LifecycleAuditContext:
    """Who publishes: the caller's SERVER-DERIVED scope, the correlation id and the intent.

    ``intent_id`` is the approved ``governance_policy_publish`` intent (required to publish; it
    becomes ``published_intent_id``). ``seed`` audits the publish as ``govpolicy.seed`` (the
    ``NS_ENV=local`` loader only).
    """

    scope: IdentityScope
    correlation_id: str
    intent_id: str | None = None
    channel: Channel | None = "worker"
    seed: bool = False


@dataclass(frozen=True, slots=True)
class LifecycleOutcome:
    """Result of a publish or retire: the stored version, its bindings and the projection."""

    stored: StoredPolicy
    bindings: tuple[StoredBinding, ...]
    projection: ProjectionResult
    audit_id: str
    bindings_reason: str | None = None


@dataclass(frozen=True, slots=True)
class ReconcileOutcome:
    """What :meth:`PolicyLifecycle.reconcile` found and repaired for one published version."""

    policy_id: str
    bindings: int
    bindings_reason: str | None
    projection: ProjectionResult


def _principal_id(scope: IdentityScope) -> str:
    principal = scope.to_contract().principal.principal_id
    return str(getattr(principal, "root", principal))


def _reason(exc: BaseException) -> str:
    reason = getattr(exc, "reason", None) if isinstance(exc, NeuroSphereError) else None
    return reason if isinstance(reason, str) and reason else "error"


# --- the lifecycle ------------------------------------------------------------------------------


class PolicyLifecycle:
    """Publishes and retires policy versions (see the module docstring for the order)."""

    def __init__(
        self,
        policies: PolicyDefinitionStore,
        bindings: BindingStore,
        audit: AuditRepository,
        registry: RuleEvaluatorRegistry,
        catalog: CatalogRepository,
        *,
        clock: Clock = _utc_now,
    ) -> None:
        self._policies = policies
        self._bindings = bindings
        self._audit = audit
        self._registry = registry
        self._catalog = catalog
        self._clock = clock

    @property
    def registry(self) -> RuleEvaluatorRegistry:
        return self._registry

    def check_publishable(self, policy: PolicyDefinition) -> None:
        """The dry run against this lifecycle's registry (see :func:`check_publishable`)."""
        check_publishable(policy, self._registry)

    async def _load(self, scope: IdentityScope, policy_id: str, version: int) -> StoredPolicy:
        stored = await self._policies.get(scope.customer_id, policy_id, version=version)
        if (
            stored is None
            or stored.policy.cloud.root != scope.cloud
            or stored.policy.domain_id.root not in scope.allowed_domains
        ):
            raise GovernancePolicyNotFoundError(POLICY_NOT_FOUND)
        return stored

    def _audit_context(self, ctx: LifecycleAuditContext, operation: str) -> AuditContext:
        return AuditContext.from_scope(
            ctx.scope,
            correlation_id=ctx.correlation_id,
            operation=operation,
            channel=ctx.channel,
            intent_id=ctx.intent_id,
        )

    async def publish(
        self,
        policy_id: str,
        version: int,
        *,
        expected_etag: str,
        audit_ctx: LifecycleAuditContext,
        expected_digest: str | None = None,
    ) -> LifecycleOutcome:
        """Publish one draft version (the module docstring lists every check)."""
        if audit_ctx.intent_id is None:
            raise InvalidSchemaError(
                "publishing needs the approved intent id",
                errors=[ValidationIssue("/intent_id", "required")],
                reason=INTENT_REQUIRED,
            )
        scope = audit_ctx.scope
        stored = await self._load(scope, policy_id, version)
        policy = validate_policy(stored.policy)
        if stored.etag != expected_etag:
            raise GovernancePolicyStaleError(POLICY_MODIFIED)
        if expected_digest is not None and expected_digest != policy_digest(policy):
            raise GovernancePolicyStaleError(POLICY_MODIFIED, "the version changed since confirm")
        if policy.status == "published":
            raise PolicyPublishedError()
        if policy.status == "retired":
            raise GovernancePolicyStaleError(POLICY_RETIRED, "a retired version stays retired")
        self.check_publishable(policy)
        operation = OPERATION_SEED if audit_ctx.seed else OPERATION_PUBLISH
        ctx = self._audit_context(audit_ctx, operation)
        chain = governance_policy_chain_id(scope.customer_id)
        subject = self._subject(policy)
        before = await self._audit.append(chain, build_before(ctx, subject))
        audit_id = str(before.audit_id.root)
        try:
            published = await self._policies.mark_published(
                scope.customer_id,
                policy_id,
                version,
                if_match=expected_etag,
                published_at=self._clock(),
                intent_id=audit_ctx.intent_id,
                audit_id=audit_id,
            )
        except Exception as exc:
            await self._audit.append(
                chain,
                build_after(ctx, subject, result="failed", verified=False, detail=_reason(exc)),
            )
            raise
        bindings, bindings_reason = await self._ensure_bindings(scope, published.policy)
        projection = await project_policy(self._catalog, scope, published.policy, now=self._clock())
        await self._audit.append(
            chain,
            build_after(
                ctx,
                subject,
                result="succeeded",
                verified=True,
                detail=self._detail("published", bindings, bindings_reason, projection),
            ),
        )
        return LifecycleOutcome(
            stored=published,
            bindings=bindings,
            projection=projection,
            audit_id=audit_id,
            bindings_reason=bindings_reason,
        )

    async def retire(
        self,
        policy_id: str,
        version: int,
        *,
        expected_etag: str,
        audit_ctx: LifecycleAuditContext,
        expected_digest: str | None = None,
    ) -> LifecycleOutcome:
        """Retire one published version; the catalog entity becomes ``deprecated`` unless
        another version of the policy is still published (that one is projected instead)."""
        scope = audit_ctx.scope
        stored = await self._load(scope, policy_id, version)
        policy = stored.policy
        if stored.etag != expected_etag:
            raise GovernancePolicyStaleError(POLICY_MODIFIED)
        if expected_digest is not None and expected_digest != policy_digest(policy):
            raise GovernancePolicyStaleError(POLICY_MODIFIED, "the version changed since confirm")
        if policy.status == "retired":
            raise GovernancePolicyStaleError(POLICY_RETIRED, "already retired")
        if policy.status != "published":
            raise GovernancePolicyStaleError(POLICY_NOT_PUBLISHED, "only a published version")
        ctx = self._audit_context(audit_ctx, OPERATION_RETIRE)
        chain = governance_policy_chain_id(scope.customer_id)
        subject = self._subject(policy)
        before = await self._audit.append(chain, build_before(ctx, subject))
        try:
            retired = await self._policies.mark_retired(
                scope.customer_id, policy_id, version, if_match=expected_etag
            )
        except Exception as exc:
            await self._audit.append(
                chain,
                build_after(ctx, subject, result="failed", verified=False, detail=_reason(exc)),
            )
            raise
        still = await self._still_published(scope.customer_id, policy_id)
        if still is not None:
            projection = await project_policy(self._catalog, scope, still, now=self._clock())
        else:
            projection = await deprecate_policy_entity(
                self._catalog, scope, retired.policy, now=self._clock()
            )
        await self._audit.append(
            chain,
            build_after(
                ctx,
                subject,
                result="succeeded",
                verified=True,
                detail=self._detail("retired", (), None, projection),
            ),
        )
        return LifecycleOutcome(
            stored=retired,
            bindings=(),
            projection=projection,
            audit_id=str(before.audit_id.root),
        )

    async def reconcile(self, scope: IdentityScope, policy: PolicyDefinition) -> ReconcileOutcome:
        """Re-ensure the bindings and the catalog projection of a PUBLISHED version.

        Idempotent and never raising: the evaluator calls it every tick so a binding or
        projection write that failed at publish time is retried (criterion 9).
        """
        if policy.status != "published":
            raise InvalidSchemaError("only a published version is reconciled")
        bindings, reason = await self._ensure_bindings(scope, policy)
        projection = await project_policy(self._catalog, scope, policy, now=self._clock())
        return ReconcileOutcome(
            policy_id=policy.policy_id.root,
            bindings=len(bindings),
            bindings_reason=reason,
            projection=projection,
        )

    async def _ensure_bindings(
        self, scope: IdentityScope, policy: PolicyDefinition
    ) -> tuple[tuple[StoredBinding, ...], str | None]:
        points = binding_points_for(policy)
        if not points:
            return (), None
        try:
            made = await self._bindings.ensure_bindings(
                policy, points, binding_mode_for(policy), updated_by=_principal_id(scope)
            )
        except Exception as exc:
            _log.warning(
                "govpolicy_bindings_failed policy_id=%s reason=%s",
                policy.policy_id.root,
                _reason(exc),
            )
            return (), BINDINGS_FAILED
        return tuple(made), None

    async def _still_published(self, customer_id: str, policy_id: str) -> PolicyDefinition | None:
        versions = await self._policies.versions(customer_id, policy_id)
        published = [s.policy for s in versions if s.policy.status == "published"]
        return max(published, key=lambda p: p.policy_version) if published else None

    @staticmethod
    def _subject(policy: PolicyDefinition) -> Subject:
        return make_subject(
            governance_policy_canonical_id(
                policy.cloud.root, policy.customer_id.root, policy.policy_id.root
            ),
            GOVERNANCE_POLICY_ENTITY_TYPE,
            target_version=f"v{policy.policy_version}",
            state_digest=policy_digest(policy),
        )

    @staticmethod
    def _detail(
        verb: str,
        bindings: tuple[StoredBinding, ...],
        bindings_reason: str | None,
        projection: ProjectionResult,
    ) -> str:
        parts = [
            verb,
            f"bindings={len(bindings)}",
            f"projection={projection.reason_code or projection.action}",
        ]
        if bindings_reason is not None:
            parts.append(f"bindings_reason={bindings_reason}")
        return ":".join(parts)
