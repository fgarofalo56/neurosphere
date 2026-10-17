"""Builders for the catalog projection tests (synthetic sandbox data only, no Azure calls).

The worker scope is derived through ``ScopeDeriver`` with an in-memory policy repository for a
workload principal (``identity_type == "app"``), exactly as production derives it.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from ingestion.support import sandbox_bundle  # type: ignore[import-not-found]
from neurosphere_contracts.catalog.v1.edge_override import EdgeOverride
from neurosphere_contracts.telemetry.v1.telemetry_event import TelemetryEvent
from neurosphere_core.auth.jwt import VerifiedClaims
from neurosphere_core.auth.scope import (
    InMemoryPolicyRepository,
    NoRevocationCheck,
    PolicyHead,
    PolicyRoleAssignment,
    PrincipalPolicy,
    PrincipalPseudonymizer,
    PseudonymKey,
    Role,
    ScopeDerivationConfig,
    ScopeDeriver,
    principal_document_id,
)
from neurosphere_core.catalog import CatalogRepository, InMemoryReviewQueue
from neurosphere_core.catalog.repo import InMemoryCatalogRepository
from neurosphere_core.cloud import CloudName
from neurosphere_core.errors import DependencyTransientError, StaleVersionError
from neurosphere_core.scope import IdentityScope
from neurosphere_workers.ingestion.models import compute_doc_id
from neurosphere_workers.projections.catalog import (
    CatalogProjection,
    InMemoryTraceEventSource,
    LoadedEvent,
    WorkloadScopeProvider,
)
from neurosphere_workers.projections.outbox import (
    SINK_CATALOG,
    InMemoryCheckpointStore,
    InMemoryOutboxStore,
    OutboxEntry,
    OutboxReader,
)

Doc = dict[str, Any]

CUSTOMER = "synthco"
TENANT = "0f1e2d3c-4b5a-4968-8776-a5b4c3d2e1f0"
WORKER_OBJECT_ID = "6c1d2e3f-4a5b-4c6d-8e7f-90a1b2c3d4e5"
AUDITOR_OBJECT_ID = "7d2e3f40-5b6c-4d7e-8f90-a1b2c3d4e5f6"
KEY_REFERENCE = "https://ns-test-kv.vault.azure.net/secrets/principal-pseudonym-key"
NOW = datetime(2026, 11, 1, 12, 0, 0, tzinfo=UTC)


def event_time(doc: Doc) -> str:
    return str(doc["event_time"])


def trace_with_delegation() -> list[Doc]:
    """All spans of one sandbox trace that has delegation, a model call and a tool call."""
    telemetry, _ = sandbox_bundle()
    traces: dict[str, list[Doc]] = {}
    for doc in telemetry:
        traces.setdefault(doc["trace_id"], []).append(doc)
    for trace_id in sorted(traces):
        spans = traces[trace_id]
        kinds = {d["span_kind"] for d in spans}
        if {"delegation", "model_call", "tool_call"} <= kinds:
            return sorted(spans, key=event_time)
    raise AssertionError("sandbox bundle has no delegation trace")


def loaded(doc: Doc) -> LoadedEvent:
    event = TelemetryEvent.model_validate(doc)
    return LoadedEvent(
        compute_doc_id(event.customer_id.root, event.source_id.root, event.event_id.root), event
    )


def outbox_entry(item: LoadedEvent, **overrides: Any) -> OutboxEntry:
    fields: dict[str, Any] = {
        "id": item.doc_id,
        "customer_id": item.event.customer_id.root,
        "kind": "event",
        "ref_id": item.doc_id,
        "entity": "event",
        "source_id": item.event.source_id.root,
        "event_kind": "telemetry",
        "occurred_at": item.event.event_time.root,
    }
    fields.update(overrides)
    return OutboxEntry.model_validate(fields)


def _pseudonymizer() -> PrincipalPseudonymizer:
    return PrincipalPseudonymizer(PseudonymKey(bytes(range(32)), reference=KEY_REFERENCE))


def make_claims(object_id: str, identity_type: str = "app") -> VerifiedClaims:
    now = datetime.now(UTC)
    return VerifiedClaims(
        issuer_kind="entra",
        cloud=CloudName.COMMERCIAL,
        issuer=f"https://login.microsoftonline.com/{TENANT}/v2.0",
        audience="api://neurosphere-test-api",
        tenant_id=TENANT,
        object_id=object_id,
        subject="subject-" + object_id[:8],
        token_version="2.0",  # noqa: S106 - JWT version label, not a secret
        issued_at=now - timedelta(seconds=60),
        not_before=now - timedelta(seconds=60),
        expires_at=now + timedelta(hours=1),
        identity_type=identity_type,  # type: ignore[arg-type]
    )


@dataclass(slots=True)
class StaticClaims:
    claims_: VerifiedClaims
    calls: int = 0

    async def claims(self) -> VerifiedClaims:
        self.calls += 1
        return self.claims_


def build_deriver(
    domains: Sequence[str],
    *,
    worker_role: Role = Role.VIEWER,
    auditor_domains: Sequence[str] = (),
) -> ScopeDeriver:
    """A deriver whose policy store grants the worker ``worker_role`` over ``domains``.

    ``auditor_domains`` additionally grants a SECOND principal (never the worker) the
    time-bound ``security_auditor`` role so tests can read raw observations.
    """
    pseudonymizer = _pseudonymizer()
    repo = InMemoryPolicyRepository()
    repo.put_head(PolicyHead(customer_id=CUSTOMER, policy_version="2026.10.01-1"))

    def put(
        object_id: str, roles: tuple[PolicyRoleAssignment, ...], members: Sequence[str]
    ) -> None:
        pid = pseudonymizer.principal_id(
            cloud=CloudName.COMMERCIAL,
            customer_id=CUSTOMER,
            tenant_id=TENANT,
            object_id=object_id,
            kind="service_principal",
        )
        repo.put_principal(
            PrincipalPolicy(
                id=principal_document_id(pid),
                customer_id=CUSTOMER,
                principal_id=pid,
                domain_memberships=tuple(members),
                role_assignments=roles,
            )
        )

    put(
        WORKER_OBJECT_ID,
        (
            PolicyRoleAssignment(
                assignment_id="ra-worker", role=worker_role, domain_ids=tuple(domains)
            ),
        ),
        domains,
    )
    if auditor_domains:
        put(
            AUDITOR_OBJECT_ID,
            (
                PolicyRoleAssignment(
                    assignment_id="ra-read", role=Role.VIEWER, domain_ids=tuple(auditor_domains)
                ),
                PolicyRoleAssignment(
                    assignment_id="ra-auditor",
                    role=Role.SECURITY_AUDITOR,
                    domain_ids=tuple(auditor_domains),
                    expires_at=datetime.now(UTC) + timedelta(hours=2),
                ),
            ),
            auditor_domains,
        )
    cfg = ScopeDerivationConfig(cloud=CloudName.COMMERCIAL, tenant_id=TENANT, customer_id=CUSTOMER)
    return ScopeDeriver(
        cfg,
        policy_repository=repo,
        pseudonymizer=pseudonymizer,
        revocation_checker=NoRevocationCheck(),
    )


class FlakyRepository:
    """Delegates to a real repository; ``put_edge`` fails after ``fail_after_puts`` successes."""

    def __init__(self, inner: CatalogRepository) -> None:
        self._inner = inner
        self.fail_after_puts: int | None = None
        self.stale_next_puts = 0  # raise StaleVersionError this many times before delegating
        self.puts = 0
        self.put_ids: list[str] = []

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)

    async def put_edge(self, scope: IdentityScope, edge: Any, expected_etag: str | None) -> Any:
        if self.fail_after_puts is not None and self.puts >= self.fail_after_puts:
            raise DependencyTransientError("injected repo outage", reason="injected")
        if self.stale_next_puts > 0:
            self.stale_next_puts -= 1
            raise StaleVersionError("injected etag race")
        saved = await self._inner.put_edge(scope, edge, expected_etag)
        self.puts += 1
        self.put_ids.append(saved.id)
        return saved


@dataclass(slots=True)
class Rig:
    docs: list[Doc]
    domains: list[str]
    inner: InMemoryCatalogRepository = field(default_factory=InMemoryCatalogRepository)
    queue: InMemoryReviewQueue = field(default_factory=InMemoryReviewQueue)
    source: InMemoryTraceEventSource = field(default_factory=InMemoryTraceEventSource)
    outbox: InMemoryOutboxStore = field(default_factory=InMemoryOutboxStore)
    checkpoints: InMemoryCheckpointStore = field(default_factory=InMemoryCheckpointStore)
    repo: FlakyRepository = field(init=False)
    reader: OutboxReader = field(init=False)
    projection: CatalogProjection = field(init=False)
    deriver: ScopeDeriver = field(init=False)
    items: list[LoadedEvent] = field(init=False)

    def __post_init__(self) -> None:
        self.repo = FlakyRepository(self.inner)
        self.deriver = build_deriver(self.domains, auditor_domains=self.domains)
        self.reader = OutboxReader(self.outbox, self.checkpoints, batch_size=3)
        self.items = [loaded(d) for d in self.docs]
        for item in self.items:
            self.source.add(item)
        self.projection = CatalogProjection(
            repository=self.repo,  # type: ignore[arg-type]
            review_queue=self.queue,
            source=self.source,
            scope_provider=WorkloadScopeProvider(
                self.deriver, StaticClaims(make_claims(WORKER_OBJECT_ID))
            ),
            clock=lambda: NOW,
        )

    async def fill_outbox(self) -> None:
        for item in self.items:
            await self.outbox.append(outbox_entry(item))

    async def drain(self) -> Any:
        return await self.reader.drain(SINK_CATALOG, CUSTOMER, self.projection.handle)

    async def auditor_scope(self) -> IdentityScope:
        provider = WorkloadScopeProvider(self.deriver, StaticClaims(make_claims(AUDITOR_OBJECT_ID)))
        return await provider.get()

    async def worker_scope(self) -> IdentityScope:
        return await self.projection._scopes.get()


def domains_of(docs: Sequence[Doc]) -> list[str]:
    return sorted({d["domain_id"] for d in docs if d.get("domain_id")})


def lock_override(edge: Any, *, decided_at: str, confidence: float) -> EdgeOverride:
    """A steward lock of ``edge`` at ``confidence`` valid well past ``NOW``."""
    steward = f"{edge.cloud.root}:{edge.customer_id.root}:entra:person:psn_0123456789abcdef"
    return EdgeOverride.model_validate(
        {
            "schema_version": "1.0.0",
            "id": f"{edge.cloud.root}:{edge.customer_id.root}:neurosphere:edge_override:lock-1",
            "edge_id": edge.id,
            "relation_type": edge.relation_type,
            "expected_edge_version": edge.version.root,
            "expected_edge_etag": edge.etag.root,
            "cloud": edge.cloud.root,
            "customer_id": edge.customer_id.root,
            "domain_id": edge.domain_id.root,
            "decision": "lock",
            "actor": steward,
            "reason": "Confirmed by steward.",
            "decided_at": decided_at,
            "lock": {
                "locked": True,
                "reason": "Confirmed by steward.",
                "expiry": "2027-06-01T00:00:00Z",
                "actor": steward,
            },
            "set_confidence": confidence,
            "set_validity": None,
            "add_evidence_ids": [],
        }
    )
