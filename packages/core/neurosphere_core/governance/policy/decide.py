"""The in-process decision function (PRP-105 item 4, acceptance criterion 7).

:meth:`PolicyDecider.decide` answers "allow, deny or audit" for one
:class:`~neurosphere_contracts.policy.v1.policy_decision_request.PolicyDecisionRequest` at one
enforcement point. The later enforcement points (PRP-112 gateway, PRP-113 tool call and MCP,
PRP-114 workload API and SDK guard, PRP-108 registration) call it; this PRP blocks nothing.

Snapshot
    The decider holds one IMMUTABLE snapshot per (cloud, customer): the published policies
    (highest published version each), their enforcement bindings and the APPROVED exceptions.
    It is refreshed when it is older than ``EnforcementSetting.decision_cache_ttl_seconds``
    (PRP-99 stored setting, default 60 s; there is no environment variable: the caller passes a
    settings provider, and until PRP-108/109 make the ``enforcement`` setting loadable the
    default provider returns ``EnforcementSetting()``), on :meth:`PolicyDecider.invalidate`, and
    when a caller's scope sees a domain whose exceptions the snapshot has not loaded yet.

    A refresh failure keeps the last snapshot and marks every answer ``degraded`` with reason
    ``stale_snapshot`` until a refresh succeeds. With no snapshot at all the answer is
    ``effect: audit``, ``mode: audit``, ``degraded: true``, reason ``snapshot_unavailable`` and a
    zero cache lifetime. Why ``audit`` and not ``allow`` or ``deny``: a store outage must never
    block (never ``deny`` from a failure; GD-8 has the SDK fail open), but a bare ``allow`` is
    what a clean, fully evaluated pass also returns, so a caller that ignores ``degraded`` would
    record nothing; ``audit`` says "proceed, but this was not verified", which is the GD-7
    default mode. A degraded answer always carries ``cache_ttl_seconds: 0`` so it is re-asked.

Evaluation (the request-evaluable subset only)
    ``model_allow_list``, ``data_sensitivity_access``, ``residency``,
    ``registration_required``, ``required_approval`` and ``required_owner``, and only at a point
    the rule kind can bind to (:data:`~.models.POINTS_BY_RULE_KIND`). Each kind looks at the
    request's subject ids, model, data asset ids and access mode; catalog facts (sensitivity
    categories, residency, approval state, owners) come from at most
    :data:`MAX_CATALOG_LOOKUPS` bounded ``get_entity`` / ``list_edges_by_node`` reads through
    the caller's scope. Without a catalog, or when a read fails, a catalog-dependent rule is
    unassessed (never a breach) and the answer says ``catalog_unavailable``.

Combination
    A rule that matched is resolved against the policy's binding for the request's
    ``decision_point`` (a binding whose ``target`` is one of the request's subjects wins over the
    null-target binding; among several, the strictest mode): ``off`` or no binding at that
    point -> ignored; an approved, unexpired exception for every breaking subject (in a domain
    the scope sees) -> the match is ``allow`` and the exception id is reported; otherwise
    ``enforce`` -> ``deny`` and ``audit`` -> ``audit``. The overall effect is ``deny`` if any
    match denies, else ``audit`` if any match audits, else ``allow`` (no match -> ``allow``).

Scope
    Only policies the caller's SERVER-DERIVED scope covers are considered: a domain policy
    whose domain is in ``allowed_domains``, and a customer-wide policy (the customer-control
    domain) only through the non-control domains the scope sees; a policy of another cloud or
    customer never. A subject id of another cloud or customer is ignored; a subject in a domain
    the scope cannot see reads as missing (the catalog returns ``None`` for both), so the
    answer is identical to the missing case. Nothing in the response names a subject: matches
    carry policy and rule ids only, and ``policy_set_digest`` covers just the policies in
    scope. A resolved entity is governed by a domain policy only when it lives in that domain;
    a subject with no catalog entity (an unregistered agent, a model known only by name) is
    governed by every in-scope policy (ASSUMPTION, runbook).

Known limits
    A subject with no catalog entity in the caller's view is governed by every in-scope policy,
    and a subject in a domain the scope cannot see reads exactly like that. So under a future
    ``enforce`` binding, ``registration_required`` could deny an agent that IS registered, but
    in a domain the caller cannot see. Today nothing binds ``enforce`` at a live point; the
    enforcement PRPs (PRP-112 gateway, PRP-113 tool call and MCP) must account for it before
    they do.

Writes
    :meth:`PolicyDecider.decide` performs no store write and no unbounded read. The audit
    record ``govpolicy.decide`` (written only for ``deny`` and audit-mode would-deny, never per
    ``allow``) is the job of an optional injected :class:`DecisionAuditRecorder`;
    :class:`AuditDecisionRecorder` is the one backed by the audit repository. A recorder
    failure is logged and never changes the answer.
"""

from __future__ import annotations

import asyncio
import builtins
import hashlib
import json
import logging
import uuid
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from types import MappingProxyType
from typing import Final, Literal, Protocol, runtime_checkable

from neurosphere_contracts.admin.v1.system_setting import EnforcementSetting
from neurosphere_contracts.catalog.v1.agent import Agent
from neurosphere_contracts.catalog.v1.agent_version import AgentVersion
from neurosphere_contracts.catalog.v1.model_deployment import ModelDeployment

from neurosphere_core.audit import AuditContext, AuditRepository, build_after, make_subject
from neurosphere_core.audit.builders import Channel
from neurosphere_core.auth.scope.permissions import customer_control_domain_id
from neurosphere_core.catalog.protocol import CatalogEntity, CatalogRepository
from neurosphere_core.governance.policy.ids import NEUROSPHERE_SOURCE, governance_policy_chain_id
from neurosphere_core.governance.policy.models import (
    POINTS_BY_RULE_KIND,
    DataSensitivityAccessParams,
    EnforcementBinding,
    EnforcementModeName,
    ModelAllowListParams,
    PolicyDecisionMatch,
    PolicyDecisionRequest,
    PolicyDecisionResponse,
    PolicyDefinition,
    PolicyRule,
    RegistrationRequiredParams,
    RequiredApprovalParams,
    RequiredOwnerParams,
    ResidencyParams,
)
from neurosphere_core.governance.policy.rules.approval import APPROVED, approval_state
from neurosphere_core.governance.policy.rules.base import (
    RuleContext,
    RuleEvaluationError,
    RunBudget,
    params_as,
    strings_of,
    text_of,
)
from neurosphere_core.governance.policy.rules.model_allow_list import telemetry_model_id
from neurosphere_core.governance.policy.rules.required_owner import OWNED_ENTITY_TYPES
from neurosphere_core.governance.policy.rules.residency import residency_verdict
from neurosphere_core.governance.policy.rules.scan import AppliesTo, node_edges
from neurosphere_core.governance.policy.store import (
    MAX_DOMAIN_FILTER,
    ExceptionFilters,
    StoredBinding,
    StoredException,
    StoredPolicy,
)
from neurosphere_core.paging import Page, PageRequest
from neurosphere_core.paging.models import MAX_PAGE_SIZE
from neurosphere_core.scope import IdentityScope

__all__ = [
    "CATALOG_UNAVAILABLE",
    "DECIDABLE_KINDS",
    "DECISION_ENTITY_TYPE",
    "EXCEPTIONS_PARTIAL",
    "EXCEPTION_APPLIED",
    "MATCHES_TRUNCATED",
    "MAX_CATALOG_LOOKUPS",
    "MAX_EXCEPTION_DOMAINS",
    "NO_RULE_MATCHED",
    "OPERATION_DECIDE",
    "RULE_MATCHED_AUDIT",
    "RULE_MATCHED_ENFORCE",
    "SNAPSHOT_UNAVAILABLE",
    "STALE_SNAPSHOT",
    "AuditDecisionRecorder",
    "BindingReader",
    "DecisionAuditRecorder",
    "ExceptionReader",
    "MatchBinding",
    "PolicyDecider",
    "PolicyDecision",
    "PublishedPolicyReader",
    "SettingsProvider",
]

OPERATION_DECIDE: Final = "govpolicy.decide"
#: Entity type of the audit subject of one decision (``...:neurosphere:policy_decision:<id>``).
DECISION_ENTITY_TYPE: Final = "policy_decision"

# --- reason codes (snake_case, never naming a subject) ------------------------------------------
NO_RULE_MATCHED: Final = "no_rule_matched"
RULE_MATCHED_ENFORCE: Final = "rule_matched_enforce"
RULE_MATCHED_AUDIT: Final = "rule_matched_audit"
EXCEPTION_APPLIED: Final = "exception_applied"
STALE_SNAPSHOT: Final = "stale_snapshot"
SNAPSHOT_UNAVAILABLE: Final = "snapshot_unavailable"
CATALOG_UNAVAILABLE: Final = "catalog_unavailable"
EXCEPTIONS_PARTIAL: Final = "exceptions_partial"
MATCHES_TRUNCATED: Final = "matches_truncated"

#: The request-evaluable subset (item 4). ``content_rule`` and the later kinds are detective only.
DECIDABLE_KINDS: Final = frozenset(
    {
        "model_allow_list",
        "data_sensitivity_access",
        "residency",
        "registration_required",
        "required_approval",
        "required_owner",
    }
)

#: Catalog reads one decision may make (entities plus owner edge pages).
MAX_CATALOG_LOOKUPS: Final = 256
#: Domains whose approved exceptions one snapshot may hold.
MAX_EXCEPTION_DOMAINS: Final = 2000
#: Exception pages read per domain chunk at refresh (``MAX_PAGE_SIZE`` rows each).
MAX_EXCEPTION_PAGES: Final = 20
#: Seconds between refresh attempts after a failure (never more often than the TTL needs).
REFRESH_RETRY_SECONDS: Final = 5.0
_MAX_MATCHES: Final = 20
_MAX_REASONS: Final = 8
_OWNER_BUDGET_SUBJECTS: Final = 200
_OWNER_BUDGET_SECONDS: Final = 2.0
_SCHEMA_VERSION: Final = "1.2.0"
_EFFECT_RANK: Final[Mapping[str, int]] = MappingProxyType({"deny": 0, "audit": 1, "allow": 2})
_MODE_RANK: Final[Mapping[str, int]] = MappingProxyType({"enforce": 2, "audit": 1, "off": 0})
_REASON_ORDER: Final = (
    SNAPSHOT_UNAVAILABLE,
    STALE_SNAPSHOT,
    EXCEPTIONS_PARTIAL,
    CATALOG_UNAVAILABLE,
    RULE_MATCHED_ENFORCE,
    RULE_MATCHED_AUDIT,
    EXCEPTION_APPLIED,
    MATCHES_TRUNCATED,
    NO_RULE_MATCHED,
)
_ACCESS_MODES: Final[Mapping[str, frozenset[str]]] = MappingProxyType(
    {
        "read": frozenset({"read"}),
        "write": frozenset({"write"}),
        "read_or_write": frozenset({"read", "write"}),
    }
)

Effect = Literal["allow", "deny", "audit"]
SettingsProvider = Callable[[], EnforcementSetting]
IdFactory = Callable[[], str]

_log = logging.getLogger(__name__)


def _default_settings() -> EnforcementSetting:
    return EnforcementSetting()


def _uuid4() -> str:
    return str(uuid.uuid4())


def _timestamp(moment: datetime) -> str:
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)


def _mode_of(binding: EnforcementBinding | None) -> EnforcementModeName:
    """A binding's mode (``audit`` when unset, the GD-7 default); ``off`` without a binding."""
    if binding is None:
        return "off"
    return binding.mode.root if binding.mode is not None else "audit"


def _digest(material: object) -> str:
    raw = json.dumps(material, separators=(",", ":"), sort_keys=True)
    return "sha256:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()


# --- read ports (the snapshot reads only; nothing here can write) --------------------------------


@runtime_checkable
class PublishedPolicyReader(Protocol):
    """The read of :class:`~.store.PolicyDefinitionStore` the snapshot needs."""

    async def list_published(
        self, customer_id: str, domain_ids: Sequence[str] | None = None, *, limit: int = ...
    ) -> builtins.list[StoredPolicy]: ...


@runtime_checkable
class BindingReader(Protocol):
    """The read of :class:`~.store.BindingStore` the snapshot needs."""

    async def list(self, customer_id: str) -> builtins.list[StoredBinding]: ...


@runtime_checkable
class ExceptionReader(Protocol):
    """The read of :class:`~.store.ExceptionStore` the snapshot needs."""

    async def list(
        self, customer_id: str, filters: ExceptionFilters, page: PageRequest
    ) -> Page[StoredException]: ...


# --- results ------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class MatchBinding:
    """The binding that decided one match (``binding_id`` ``None``: no binding at the point)."""

    policy_id: str
    rule_id: str
    binding_id: str | None
    mode: EnforcementModeName


@dataclass(frozen=True, slots=True)
class PolicyDecision:
    """:class:`PolicyDecisionResponse` plus what the contract has no field for.

    ``applied_exception_ids`` are the exceptions that turned a match into ``allow`` (PRP-99's
    response has no field for them; the route and the audit record use these). ``bindings`` is
    the binding mode per matched rule at the request's point. ``would_deny`` is True when a
    match was not excepted (``deny`` under ``enforce``, audit-mode would-deny under ``audit``):
    exactly the decisions that get a ``govpolicy.decide`` audit record.
    """

    response: PolicyDecisionResponse
    applied_exception_ids: tuple[str, ...] = ()
    bindings: tuple[MatchBinding, ...] = ()
    would_deny: bool = False


@runtime_checkable
class DecisionAuditRecorder(Protocol):
    """Records ``govpolicy.decide`` for ``deny`` and audit-mode would-deny (never ``allow``)."""

    async def record(
        self, scope: IdentityScope, request: PolicyDecisionRequest, decision: PolicyDecision
    ) -> None: ...


class AuditDecisionRecorder:
    """:class:`DecisionAuditRecorder` over the audit repository.

    One ``after`` record on ``<customer>.governance-policy``, operation ``govpolicy.decide``,
    subject ``<cloud>:<customer>:neurosphere:policy_decision:<decision_id>`` whose state digest
    covers the effect, the mode, the matched policy and rule ids, the applied exception ids and
    the policy set digest. Ids and codes only, never request content.
    """

    def __init__(self, audit: AuditRepository, *, channel: Channel | None = "rest") -> None:
        self._audit = audit
        self._channel: Channel | None = channel

    async def record(
        self, scope: IdentityScope, request: PolicyDecisionRequest, decision: PolicyDecision
    ) -> None:
        response = decision.response
        decision_id = response.decision_id.root
        subject = make_subject(
            ":".join(
                (
                    scope.cloud,
                    scope.customer_id,
                    NEUROSPHERE_SOURCE,
                    DECISION_ENTITY_TYPE,
                    decision_id,
                )
            ),
            DECISION_ENTITY_TYPE,
            state={
                "effect": response.effect,
                "mode": response.mode.root,
                "decision_point": request.decision_point.root,
                "operation": request.operation,
                "matches": [
                    [m.policy_id.root, m.policy_version, m.rule_id.root, m.effect]
                    for m in response.matches
                ],
                "applied_exception_ids": list(decision.applied_exception_ids),
                "policy_set_digest": response.policy_set_digest,
            },
        )
        # Dashless: the audit content guard reads a GUID-shaped correlation id as an object id.
        ctx = AuditContext.from_scope(
            scope,
            correlation_id="govpolicy-decide-" + decision_id.replace("-", ""),
            operation=OPERATION_DECIDE,
            channel=self._channel,
        )
        detail = "effect=deny" if response.effect == "deny" else "effect=audit_would_deny"
        await self._audit.append(
            governance_policy_chain_id(scope.customer_id),
            build_after(ctx, subject, result="succeeded", verified=False, detail=detail),
        )


# --- snapshot -----------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _ActiveException:
    exception_id: str
    domain_id: str
    expires_at: datetime


ExceptionKey = tuple[str, str, str]  # (policy_id, rule_id, subject canonical id)


@dataclass(frozen=True, slots=True)
class _Snapshot:
    loaded_at: datetime
    policies: tuple[PolicyDefinition, ...]
    bindings: Mapping[str, tuple[EnforcementBinding, ...]]
    exceptions: Mapping[ExceptionKey, tuple[_ActiveException, ...]]
    exception_domains: frozenset[str]
    exceptions_partial: bool


@dataclass
class _Entry:
    """Mutable holder of one (cloud, customer) snapshot (private)."""

    snapshot: _Snapshot | None = None
    invalidated: bool = False
    failed_at: datetime | None = None
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)


# --- per-decision subject resolution -------------------------------------------------------------


Lookup = Literal["found", "missing", "unknown"]


class _Resolver:
    """Bounded, cached catalog reads through the caller's scope for ONE decision (private).

    ``found``: the entity. ``missing``: the catalog says there is none the scope can see (missing
    or out of scope, indistinguishable). ``unknown``: no catalog, a failed read or the lookup cap,
    so nothing can be concluded (never a breach).
    """

    def __init__(
        self, catalog: CatalogRepository | None, scope: IdentityScope, now: datetime
    ) -> None:
        self._catalog = catalog
        self._scope = scope
        self._now = now
        self._cache: dict[str, tuple[Lookup, CatalogEntity | None]] = {}
        self._reads = 0
        self.unavailable = False

    def _charge(self) -> bool:
        if self._reads >= MAX_CATALOG_LOOKUPS:
            self.unavailable = True
            return False
        self._reads += 1
        return True

    async def get(self, entity_id: str) -> tuple[Lookup, CatalogEntity | None]:
        if entity_id in self._cache:
            return self._cache[entity_id]
        if self._catalog is None or not self._charge():
            self.unavailable = True
            return ("unknown", None)
        try:
            entity = await self._catalog.get_entity(self._scope, entity_id)
        except Exception as exc:  # an outage is "unknown", never a breach
            _log.warning("govpolicy_decide_catalog_failed reason=%s", type(exc).__name__)
            self.unavailable = True
            return ("unknown", None)
        result: tuple[Lookup, CatalogEntity | None] = (
            ("found", entity) if entity is not None else ("missing", None)
        )
        self._cache[entity_id] = result
        return result

    async def owners(self, entity_id: str, active_only: bool) -> int | None:
        """Owners of ``entity_id`` (``owned_by`` targets); ``None`` when it cannot be read."""
        if self._catalog is None or not self._charge():
            self.unavailable = True
            return None
        ctx = RuleContext(
            scope=self._scope,
            domain_ids=self._scope.allowed_domains,
            now=self._now,
            budget=RunBudget.start(_OWNER_BUDGET_SUBJECTS, _OWNER_BUDGET_SECONDS),
        )
        try:
            edges = await node_edges(self._catalog, ctx, entity_id, "out", "owned_by")
        except Exception as exc:
            _log.warning("govpolicy_decide_catalog_failed reason=%s", type(exc).__name__)
            self.unavailable = True
            return None
        if edges is None:
            self.unavailable = True
            return None
        owners = sorted({e.target_id for e in edges})
        if not active_only:
            return len(owners)
        count = 0
        for owner_id in owners:
            status, owner = await self.get(owner_id)
            if status == "unknown":
                return None
            if owner is not None and text_of(owner.lifecycle_status) == "active":
                count += 1
        return count


@dataclass(frozen=True, slots=True)
class _Subject:
    """One request subject: canonical id, type segment, what the catalog said about it."""

    canonical_id: str
    entity_type: str
    status: Lookup
    entity: CatalogEntity | None

    @property
    def domain_id(self) -> str | None:
        if self.entity is None:
            return None
        return text_of(getattr(self.entity, "domain_id", None))


def _type_of(canonical_id: str) -> str:
    parts = canonical_id.split(":", 4)
    return parts[3] if len(parts) == 5 else "unknown"


@dataclass
class _Request:
    """The request's subjects resolved through the scope (private, one per decision)."""

    agent: _Subject | None
    agent_version: _Subject | None
    tool: _Subject | None
    mcp_server: _Subject | None
    deployment: _Subject | None
    assets: tuple[_Subject, ...]
    target_ids: frozenset[str]

    def actors(self) -> list[_Subject]:
        candidates = (self.agent_version, self.agent, self.tool, self.mcp_server)
        return [s for s in candidates if s is not None]


# --- the decider --------------------------------------------------------------------------------


@dataclass
class _RuleResult:
    breaching: tuple[str, ...]


class PolicyDecider:
    """Answers :class:`PolicyDecisionRequest` from a cached snapshot (see the module docstring).

    ``policies``, ``bindings`` and ``exceptions`` are the stores (only their reads are used);
    ``catalog`` is optional (catalog-dependent rules are unassessed without it); ``settings``
    returns the PRP-99 ``EnforcementSetting`` (default ``EnforcementSetting()``: 60 s);
    ``recorder`` writes ``govpolicy.decide`` for deny and audit-mode would-deny.
    """

    def __init__(
        self,
        policies: PublishedPolicyReader,
        bindings: BindingReader,
        exceptions: ExceptionReader,
        *,
        catalog: CatalogRepository | None = None,
        settings: SettingsProvider = _default_settings,
        recorder: DecisionAuditRecorder | None = None,
        id_factory: IdFactory = _uuid4,
        retry_seconds: float = REFRESH_RETRY_SECONDS,
    ) -> None:
        self._policies = policies
        self._bindings = bindings
        self._exceptions = exceptions
        self._catalog = catalog
        self._settings = settings
        self._recorder = recorder
        self._ids = id_factory
        self._retry = timedelta(seconds=max(0.0, retry_seconds))
        self._entries: dict[tuple[str, str], _Entry] = {}

    # -- cache control --------------------------------------------------------------------------

    def invalidate(self, customer_id: str | None = None) -> None:
        """Force a refresh on the next decision (one customer, or every cached customer).

        The last snapshot stays as the fallback if that refresh fails.
        """
        for (_, customer), entry in self._entries.items():
            if customer_id is None or customer == customer_id:
                entry.invalidated = True
                entry.failed_at = None

    def ttl_seconds(self) -> int:
        """The configured snapshot and response cache lifetime (0..3600 seconds)."""
        try:
            value = self._settings().decision_cache_ttl_seconds
        except Exception as exc:  # a broken provider falls back to the contract default
            _log.warning("govpolicy_decide_settings_failed reason=%s", type(exc).__name__)
            value = None
        ttl = EnforcementSetting().decision_cache_ttl_seconds if value is None else value
        return max(0, min(3600, int(ttl or 0)))

    def _due(self, entry: _Entry, now: datetime, ttl: int, visible: frozenset[str]) -> bool:
        snap = entry.snapshot
        if snap is None or entry.invalidated:
            return True
        age = (now - snap.loaded_at).total_seconds()
        if age < 0 or age >= ttl:
            return True
        missing = visible - snap.exception_domains
        return bool(missing) and len(snap.exception_domains) < MAX_EXCEPTION_DOMAINS

    async def _snapshot(
        self, scope: IdentityScope, now: datetime, ttl: int
    ) -> tuple[_Snapshot | None, bool]:
        """The snapshot for the scope's customer and whether it is stale."""
        key = (scope.cloud, scope.customer_id)
        entry = self._entries.setdefault(key, _Entry())
        visible = frozenset(scope.allowed_domains)
        if not self._due(entry, now, ttl, visible):
            return entry.snapshot, False
        async with entry.lock:
            if not self._due(entry, now, ttl, visible):
                return entry.snapshot, False
            if entry.failed_at is not None and now - entry.failed_at < self._retry:
                return entry.snapshot, True
            previous = entry.snapshot
            domains = set(visible)
            if previous is not None:
                domains |= previous.exception_domains
            try:
                fresh = await self._load(scope.customer_id, sorted(domains), now)
            except Exception as exc:
                _log.warning(
                    "govpolicy_decide_refresh_failed customer=%s reason=%s",
                    scope.customer_id,
                    type(exc).__name__,
                )
                entry.failed_at = now
                return entry.snapshot, True
            entry.snapshot = fresh
            entry.invalidated = False
            entry.failed_at = None
            return fresh, False

    async def _load(self, customer_id: str, domains: list[str], now: datetime) -> _Snapshot:
        published = await self._policies.list_published(customer_id)
        policies = tuple(
            s.policy
            for s in sorted(published, key=lambda s: s.policy.policy_id.root)
            if s.policy.status == "published"
        )
        live = {p.policy_id.root for p in policies}
        by_policy: dict[str, list[EnforcementBinding]] = {}
        for stored in await self._bindings.list(customer_id):
            if stored.retired or stored.binding.policy_id.root not in live:
                continue
            by_policy.setdefault(stored.binding.policy_id.root, []).append(stored.binding)
        partial = len(domains) > MAX_EXCEPTION_DOMAINS
        covered = domains[:MAX_EXCEPTION_DOMAINS]
        exceptions: dict[ExceptionKey, list[_ActiveException]] = {}
        for start in range(0, len(covered), MAX_DOMAIN_FILTER):
            chunk = tuple(covered[start : start + MAX_DOMAIN_FILTER])
            cursor: str | None = None
            for _ in range(MAX_EXCEPTION_PAGES):
                page = await self._exceptions.list(
                    customer_id,
                    ExceptionFilters(domain_ids=chunk, status="approved"),
                    PageRequest(page_size=MAX_PAGE_SIZE, cursor=cursor),
                )
                for stored in page.items:
                    self._add_exception(exceptions, stored, now)
                cursor = page.next_cursor
                if cursor is None:
                    break
            else:
                partial = True
        return _Snapshot(
            loaded_at=now,
            policies=policies,
            bindings=MappingProxyType({k: tuple(v) for k, v in sorted(by_policy.items())}),
            exceptions=MappingProxyType({k: tuple(v) for k, v in exceptions.items()}),
            exception_domains=frozenset(covered),
            exceptions_partial=partial,
        )

    @staticmethod
    def _add_exception(
        out: dict[ExceptionKey, list[_ActiveException]], stored: StoredException, now: datetime
    ) -> None:
        exc = stored.exception
        if exc.status != "approved":
            return
        expires = _parse_timestamp(exc.expires_at.root)
        if expires <= now.astimezone(UTC):
            return
        key = (exc.policy_id.root, exc.rule_id.root, exc.subject.canonical_id)
        out.setdefault(key, []).append(
            _ActiveException(exc.exception_id.root, exc.domain_id.root, expires)
        )

    # -- decide ---------------------------------------------------------------------------------

    async def decide(
        self, scope: IdentityScope, request: PolicyDecisionRequest, *, now: datetime
    ) -> PolicyDecisionResponse:
        """Allow, deny or audit for ``request`` under the caller's derived ``scope``."""
        decision = await self.decide_detail(scope, request, now=now)
        return decision.response

    async def decide_detail(
        self, scope: IdentityScope, request: PolicyDecisionRequest, *, now: datetime
    ) -> PolicyDecision:
        """:meth:`decide` plus the applied exception ids and the binding per match."""
        if now.tzinfo is None:
            raise ValueError("now must be timezone-aware")
        ttl = self.ttl_seconds()
        snapshot, stale = await self._snapshot(scope, now, ttl)
        if snapshot is None:
            return PolicyDecision(
                response=self._response(
                    now,
                    effect="audit",
                    mode="audit",
                    matches=[],
                    reasons={SNAPSHOT_UNAVAILABLE},
                    ttl=0,
                    digest=_digest([]),
                    degraded=True,
                )
            )
        decision = await self._evaluate(scope, request, snapshot, now, ttl, stale)
        if decision.would_deny and self._recorder is not None:
            try:
                await self._recorder.record(scope, request, decision)
            except Exception as exc:  # the answer never depends on the audit write
                _log.warning("govpolicy_decide_audit_failed reason=%s", type(exc).__name__)
        return decision

    def _in_scope(self, scope: IdentityScope, snapshot: _Snapshot) -> list[PolicyDefinition]:
        visible = set(scope.allowed_domains)
        control = customer_control_domain_id(scope.cloud, scope.customer_id)
        wide = bool(visible - {control})
        out: list[PolicyDefinition] = []
        for policy in snapshot.policies:
            if policy.cloud.root != scope.cloud or policy.customer_id.root != scope.customer_id:
                continue
            if policy.mode is not None and policy.mode.root == "off":
                continue
            domain = policy.domain_id.root
            if (domain == control and wide) or (domain != control and domain in visible):
                out.append(policy)
        return out

    async def _resolve(
        self, scope: IdentityScope, request: PolicyDecisionRequest, resolver: _Resolver
    ) -> _Request:
        prefix = f"{scope.cloud}:{scope.customer_id}:"

        async def one(raw: object) -> _Subject | None:
            canonical = text_of(raw)
            if canonical is None or not canonical.startswith(prefix):
                return None  # another cloud or customer: never considered, never described
            status, entity = await resolver.get(canonical)
            return _Subject(canonical, _type_of(canonical), status, entity)

        assets: list[_Subject] = []
        for raw in request.data_asset_ids or []:
            subject = await one(raw)
            if subject is not None and subject.canonical_id not in {a.canonical_id for a in assets}:
                assets.append(subject)
        deployment = (
            await one(request.model.deployment_id)
            if request.model is not None and request.model.deployment_id is not None
            else None
        )
        resolved = _Request(
            agent=await one(request.agent_id) if request.agent_id is not None else None,
            agent_version=(
                await one(request.agent_version_id)
                if request.agent_version_id is not None
                else None
            ),
            tool=await one(request.tool_id) if request.tool_id is not None else None,
            mcp_server=(
                await one(request.mcp_server_id) if request.mcp_server_id is not None else None
            ),
            deployment=deployment,
            assets=tuple(assets),
            target_ids=frozenset(),
        )
        resolved.target_ids = frozenset(
            s.canonical_id for s in (*resolved.actors(), resolved.deployment) if s is not None
        )
        return resolved

    async def _evaluate(
        self,
        scope: IdentityScope,
        request: PolicyDecisionRequest,
        snapshot: _Snapshot,
        now: datetime,
        ttl: int,
        stale: bool,
    ) -> PolicyDecision:
        point = request.decision_point.root
        visible = frozenset(scope.allowed_domains)
        control = customer_control_domain_id(scope.cloud, scope.customer_id)
        policies = self._in_scope(scope, snapshot)
        resolver = _Resolver(self._catalog, scope, now)
        subjects = await self._resolve(scope, request, resolver)
        reasons: set[str] = set()
        if stale:
            reasons.add(STALE_SNAPSHOT)
        partial = snapshot.exceptions_partial or bool(visible - snapshot.exception_domains)
        if partial:
            reasons.add(EXCEPTIONS_PARTIAL)
        matches: list[PolicyDecisionMatch] = []
        bindings: list[MatchBinding] = []
        applied: dict[str, None] = {}
        digest_rows: list[list[object]] = []
        point_mode: EnforcementModeName = "off"
        for policy in policies:
            binding = self._binding(snapshot, policy, point, subjects.target_ids)
            mode = _mode_of(binding)
            digest_rows.append(
                [
                    policy.policy_id.root,
                    policy.policy_version,
                    policy.content_sha256,
                    binding.binding_id.root if binding is not None else None,
                    mode,
                ]
            )
            if binding is None or mode == "off":
                continue
            if _MODE_RANK[mode] > _MODE_RANK[point_mode]:
                point_mode = mode
            for rule in policy.rules:
                kind = rule.kind.root
                if kind not in DECIDABLE_KINDS or point not in POINTS_BY_RULE_KIND.get(kind, ()):
                    continue
                result = await self._rule(policy, rule, request, subjects, resolver, control)
                if result is None or not result.breaching:
                    continue
                excepted = self._exceptions_for(
                    snapshot, policy, rule, result.breaching, visible, now
                )
                if excepted is not None:
                    effect: Effect = "allow"
                    for exception_id in excepted:
                        applied[exception_id] = None
                    reasons.add(EXCEPTION_APPLIED)
                elif mode == "enforce":
                    effect = "deny"
                    reasons.add(RULE_MATCHED_ENFORCE)
                else:
                    effect = "audit"
                    reasons.add(RULE_MATCHED_AUDIT)
                matches.append(
                    PolicyDecisionMatch.model_validate(
                        {
                            "policy_id": policy.policy_id.root,
                            "policy_version": policy.policy_version,
                            "rule_id": rule.rule_id.root,
                            "rule_kind": kind,
                            "effect": effect,
                        }
                    )
                )
                bindings.append(
                    MatchBinding(
                        policy.policy_id.root, rule.rule_id.root, binding.binding_id.root, mode
                    )
                )
        if resolver.unavailable:
            reasons.add(CATALOG_UNAVAILABLE)
        effects = {m.effect for m in matches}
        overall: Effect = (
            "deny" if "deny" in effects else "audit" if "audit" in effects else "allow"
        )
        if not matches:
            reasons.add(NO_RULE_MATCHED)
        order = sorted(
            range(len(matches)),
            key=lambda i: (
                _EFFECT_RANK[matches[i].effect],
                matches[i].policy_id.root,
                matches[i].rule_id.root,
            ),
        )
        if len(order) > _MAX_MATCHES:
            reasons.add(MATCHES_TRUNCATED)
        kept = order[:_MAX_MATCHES]
        degraded = stale or partial
        response = self._response(
            now,
            effect=overall,
            mode=point_mode,
            matches=[matches[i] for i in kept],
            reasons=reasons,
            ttl=0 if degraded else ttl,
            digest=_digest(sorted(digest_rows, key=lambda r: str(r[0]))),
            degraded=degraded,
        )
        return PolicyDecision(
            response=response,
            applied_exception_ids=tuple(sorted(applied)),
            bindings=tuple(bindings[i] for i in kept),
            would_deny=bool(effects & {"deny", "audit"}),
        )

    def _response(
        self,
        now: datetime,
        *,
        effect: Effect,
        mode: EnforcementModeName,
        matches: list[PolicyDecisionMatch],
        reasons: Iterable[str],
        ttl: int,
        digest: str,
        degraded: bool,
    ) -> PolicyDecisionResponse:
        wanted = set(reasons)
        codes = [r for r in _REASON_ORDER if r in wanted][:_MAX_REASONS]
        return PolicyDecisionResponse.model_validate(
            {
                "schema_version": _SCHEMA_VERSION,
                "decision_id": self._ids(),
                "decided_at": _timestamp(now),
                "effect": effect,
                "mode": mode,
                "matches": [m.model_dump(mode="json") for m in matches],
                "reason_codes": codes,
                "cache_ttl_seconds": ttl,
                "policy_set_digest": digest,
                "degraded": degraded,
            }
        )

    @staticmethod
    def _binding(
        snapshot: _Snapshot, policy: PolicyDefinition, point: str, targets: frozenset[str]
    ) -> EnforcementBinding | None:
        candidates = [
            b
            for b in snapshot.bindings.get(policy.policy_id.root, ())
            if b.point.root == point and b.domain_id.root == policy.domain_id.root
        ]
        targeted = [
            b for b in candidates if b.target is not None and b.target.canonical_id in targets
        ]
        chosen = targeted or [b for b in candidates if b.target is None]
        if not chosen:
            return None
        return max(chosen, key=lambda b: (_MODE_RANK[_mode_of(b)], b.binding_id.root))

    @staticmethod
    def _exceptions_for(
        snapshot: _Snapshot,
        policy: PolicyDefinition,
        rule: PolicyRule,
        breaching: Sequence[str],
        visible: frozenset[str],
        now: datetime,
    ) -> list[str] | None:
        """Exception ids covering EVERY breaching subject, or ``None`` when one is uncovered."""
        moment = now.astimezone(UTC)
        found: list[str] = []
        for subject_id in breaching:
            live = [
                e
                for e in snapshot.exceptions.get(
                    (policy.policy_id.root, rule.rule_id.root, subject_id), ()
                )
                if e.domain_id in visible and e.expires_at > moment
            ]
            if not live:
                return None
            live.sort(key=lambda e: (e.expires_at, e.exception_id))
            found.append(live[-1].exception_id)
        return found

    # -- one rule against the request -----------------------------------------------------------

    @staticmethod
    def _governs(policy: PolicyDefinition, subject: _Subject, control: str) -> bool:
        """True when ``policy`` covers ``subject``'s domain (unknown domain: the request's)."""
        domain = subject.domain_id
        if domain is None:
            return True
        if policy.domain_id.root == control:
            return domain != control
        return domain == policy.domain_id.root

    @staticmethod
    def _applies(applies: AppliesTo, subject: _Subject) -> bool:
        if subject.entity is not None:
            return applies.matches_entity(subject.entity)
        return applies.matches_unregistered(subject.canonical_id, subject.entity_type)

    async def _rule(
        self,
        policy: PolicyDefinition,
        rule: PolicyRule,
        request: PolicyDecisionRequest,
        subjects: _Request,
        resolver: _Resolver,
        control: str,
    ) -> _RuleResult | None:
        """Subjects breaking ``rule`` in this request; ``None`` when it cannot be assessed."""
        kind = rule.kind.root
        try:
            if kind == "model_allow_list":
                return await self._model_allow_list(
                    policy, rule, request, subjects, resolver, control
                )
            if kind == "data_sensitivity_access":
                return await self._data_access(policy, rule, request, subjects, resolver, control)
            if kind == "residency":
                return self._residency(policy, rule, subjects, control)
            if kind == "registration_required":
                return self._registration(policy, rule, subjects, control)
            if kind == "required_approval":
                return await self._approval(policy, rule, subjects, resolver, control)
            if kind == "required_owner":
                return await self._owner(policy, rule, subjects, resolver, control)
        except RuleEvaluationError as exc:
            _log.warning(
                "govpolicy_decide_rule_unusable policy_id=%s rule_id=%s reason=%s",
                policy.policy_id.root,
                rule.rule_id.root,
                exc.reason,
            )
        return None

    async def _model_allow_list(
        self,
        policy: PolicyDefinition,
        rule: PolicyRule,
        request: PolicyDecisionRequest,
        subjects: _Request,
        resolver: _Resolver,
        control: str,
    ) -> _RuleResult | None:
        params = params_as(rule, ModelAllowListParams, "model_allow_list")
        model = request.model
        if model is None:
            return None
        deployments = {text_of(d) or "" for d in params.allowed_deployment_ids or []}
        deployment = subjects.deployment
        if deployment is not None and deployment.canonical_id in deployments:
            return _RuleResult(())
        name = model.model_name
        version = model.model_version
        if deployment is not None and isinstance(deployment.entity, ModelDeployment):
            name = name or deployment.entity.model_name
            version = version or text_of(deployment.entity.model_version)
        if name is None:
            return None  # an unknown model is never a breach
        versions: dict[str, set[str | None]] = {}
        for entry in params.allowed_models or []:
            versions.setdefault(entry.model_name.strip().lower(), set()).add(entry.model_version)
        allowed = versions.get(name.strip().lower())
        if allowed is not None and (None in allowed or version is None or version in allowed):
            return _RuleResult(())
        if deployment is None and await self._allowed_by_deployment_name(
            sorted(d for d in deployments if d), name, resolver
        ):
            return _RuleResult(())
        applies = AppliesTo.of(rule)
        actors = subjects.actors()
        if actors:
            breaching = [
                a.canonical_id
                for a in actors
                if self._governs(policy, a, control) and self._applies(applies, a)
            ]
        elif deployment is not None:
            governed = self._governs(policy, deployment, control)
            breaching = (
                [deployment.canonical_id] if governed and self._applies(applies, deployment) else []
            )
        else:
            model_id = telemetry_model_id(
                policy.cloud.root, policy.customer_id.root, "model:" + name
            )
            breaching = [model_id] if applies.matches_unregistered(model_id, "model") else []
        return _RuleResult(tuple(breaching))

    @staticmethod
    async def _allowed_by_deployment_name(
        deployment_ids: list[str], name: str, resolver: _Resolver
    ) -> bool:
        wanted = name.strip().lower()
        for deployment_id in deployment_ids:
            _, entity = await resolver.get(deployment_id)
            if isinstance(entity, ModelDeployment) and entity.model_name.strip().lower() == wanted:
                return True
        return False

    async def _data_access(
        self,
        policy: PolicyDefinition,
        rule: PolicyRule,
        request: PolicyDecisionRequest,
        subjects: _Request,
        resolver: _Resolver,
        control: str,
    ) -> _RuleResult | None:
        params = params_as(rule, DataSensitivityAccessParams, "data_sensitivity_access")
        if not subjects.assets:
            return None
        if request.access is None:
            if params.access != "read_or_write":
                return None  # the access mode is unknown, so a read- or write-only rule cannot say
        elif request.access not in _ACCESS_MODES[params.access]:
            return _RuleResult(())
        wanted = {text_of(c) or "" for c in params.sensitivity_categories} - {""}
        sensitive = [
            a
            for a in subjects.assets
            if a.entity is not None
            and self._governs(policy, a, control)
            and wanted & set(strings_of(getattr(a.entity, "sensitivity_categories", None)))
        ]
        if not sensitive:
            return _RuleResult(())
        applies = AppliesTo.of(rule)
        actors = subjects.actors()
        accessor = actors[0] if actors else None
        if accessor is not None and not self._applies(applies, accessor):
            return _RuleResult(())
        if params.allowed_when == "agent_version_approved" and accessor is not None:
            state = await self._approval_state(accessor, resolver)
            if state is None:
                return None
            if state == APPROVED:
                return _RuleResult(())
        if accessor is not None:
            return _RuleResult((accessor.canonical_id,))
        return _RuleResult(tuple(a.canonical_id for a in sensitive))

    @staticmethod
    async def _approval_state(subject: _Subject, resolver: _Resolver) -> str | None:
        """The subject's approval state; ``None`` when it cannot be read."""
        if subject.status == "unknown":
            return None
        entity = subject.entity
        if isinstance(entity, AgentVersion):
            return approval_state(entity)
        if isinstance(entity, Agent):
            current = text_of(entity.current_version_id)
            if current is None:
                return "none"
            status, version = await resolver.get(current)
            if status == "unknown":
                return None
            return approval_state(version) if isinstance(version, AgentVersion) else "none"
        return "none"

    def _residency(
        self, policy: PolicyDefinition, rule: PolicyRule, subjects: _Request, control: str
    ) -> _RuleResult | None:
        params = params_as(rule, ResidencyParams, "residency")
        regions = frozenset(r.lower() for r in strings_of(params.allowed_regions))
        geographies = frozenset(strings_of(params.allowed_geographies))
        if not (regions or geographies):
            return _RuleResult(())
        applies = AppliesTo.of(rule)
        candidates = [*subjects.assets, *([subjects.deployment] if subjects.deployment else [])]
        breaching: list[str] = []
        for subject in candidates:
            entity = subject.entity
            if entity is None or entity.entity_type not in ("grounding_source", "model_deployment"):
                continue
            if not self._governs(policy, subject, control) or not applies.matches_entity(entity):
                continue
            region = text_of(getattr(entity, "residency_region", None))
            geography = text_of(getattr(entity, "residency_geography", None))
            if residency_verdict(region, geography, regions, geographies) is False:
                breaching.append(subject.canonical_id)
        return _RuleResult(tuple(breaching))

    def _registration(
        self, policy: PolicyDefinition, rule: PolicyRule, subjects: _Request, control: str
    ) -> _RuleResult | None:
        params = params_as(rule, RegistrationRequiredParams, "registration_required")
        if "agent" not in params.entity_types:
            return _RuleResult(())
        applies = AppliesTo.of(rule)
        breaching: list[str] = []
        assessed = False
        agent = subjects.agent
        if agent is not None and agent.status != "unknown":
            assessed = True
            if not isinstance(agent.entity, Agent):
                if agent.entity is None and applies.matches_unregistered(
                    agent.canonical_id, "agent"
                ):
                    breaching.append(agent.canonical_id)
        version = subjects.agent_version
        if version is not None and version.status != "unknown":
            assessed = True
            entity = version.entity
            if (
                isinstance(entity, AgentVersion)
                and entity.approval is None
                and self._governs(policy, version, control)
                and (applies.allows_type("agent") or applies.allows_type("agent_version"))
                and (
                    not applies.entity_ids
                    or bool({entity.id, entity.agent_id} & applies.entity_ids)
                )
            ):
                breaching.append(version.canonical_id)
        return _RuleResult(tuple(breaching)) if assessed else None

    async def _approval(
        self,
        policy: PolicyDefinition,
        rule: PolicyRule,
        subjects: _Request,
        resolver: _Resolver,
        control: str,
    ) -> _RuleResult | None:
        params = params_as(rule, RequiredApprovalParams, "required_approval")
        if "agent_version" not in strings_of(params.entity_types or ["agent_version"]):
            return _RuleResult(())
        version = subjects.agent_version
        if version is None and subjects.agent is not None:
            agent = subjects.agent.entity
            current = text_of(agent.current_version_id) if isinstance(agent, Agent) else None
            if current is not None:
                status, entity = await resolver.get(current)
                version = _Subject(current, "agent_version", status, entity)
        if version is None or version.status == "unknown":
            return None
        entity = version.entity
        if not isinstance(entity, AgentVersion):
            return _RuleResult(())
        if not self._governs(policy, version, control):
            return _RuleResult(())
        if not AppliesTo.of(rule).matches_entity(entity) or approval_state(entity) == APPROVED:
            return _RuleResult(())
        return _RuleResult((version.canonical_id,))

    async def _owner(
        self,
        policy: PolicyDefinition,
        rule: PolicyRule,
        subjects: _Request,
        resolver: _Resolver,
        control: str,
    ) -> _RuleResult | None:
        params = params_as(rule, RequiredOwnerParams, "required_owner")
        min_owners = params.min_owners or 1
        active_only = params.require_active_owner is not False
        applies = AppliesTo.of(rule)
        candidates = [
            *subjects.actors(),
            *([subjects.deployment] if subjects.deployment else []),
            *subjects.assets,
        ]
        breaching: list[str] = []
        unknown = False
        for subject in candidates:
            entity = subject.entity
            if subject.status == "unknown":
                unknown = True
                continue
            if entity is None or entity.entity_type not in OWNED_ENTITY_TYPES:
                continue
            if not self._governs(policy, subject, control) or not applies.matches_entity(entity):
                continue
            owners = await resolver.owners(subject.canonical_id, active_only)
            if owners is None:
                unknown = True
                continue
            if owners < min_owners:
                breaching.append(subject.canonical_id)
        if unknown and not breaching:
            return None
        return _RuleResult(tuple(breaching))
