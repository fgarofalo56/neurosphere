"""The negative-suite world (PRP-06 item 6): two customers x two domains x five roles.

Everything here is test infrastructure over the real item 1-5 implementation:

* tokens come from the item-1 dev issuer (NS_ENV=local, in-memory keys, no network);
* each customer is its own deployment (cloud + tenant + customer bound, C1/C2) with its own
  in-memory policy, revocation and audit stores, sharing one fake clock;
* the HTTP app is built by the PRP-05 factory and wired with ``configure_authz``;
* the export function, the scope-keyed cache, the search wrapper and the push gateway are small
  reference adapters that take the SAME ``IdentityScope`` object the REST routes use. They are
  test doubles for features owned by later PRPs (search: PRP-10, push: PRP-18); the negative
  suite is what those PRPs must re-run.
"""

import asyncio
import uuid
from collections.abc import Coroutine, Iterable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from functools import cache
from typing import Annotated, Any, NamedTuple

from fastapi import APIRouter, Body, Depends, FastAPI, Header, Query
from fastapi.testclient import TestClient
from neurosphere_api.app import create_app
from neurosphere_api.audit import build_router as build_audit_router
from neurosphere_api.authz import (
    DeniedAttempt,
    audit_require_permission,
    configure_authz,
    domain_from_path,
    require,
    resource_from_path,
    scope_cache_key,
)
from neurosphere_contracts.query.v1.budget import Budget
from neurosphere_core.audit import (
    AuditContext,
    AuditRepository,
    InMemoryAuditStore,
    build_allowed,
    build_denied,
    make_subject,
)
from neurosphere_core.audit.builders import DenialCode
from neurosphere_core.auth.jwt import DevIssuer, JwksCache, JwtConfig, JwtValidator, entra_jwks_uri
from neurosphere_core.auth.revocation import (
    CachedRevocationChecker,
    InMemoryRevocationStore,
    RevocationAuditEvent,
    RevocationHookRegistry,
    RevocationOutcome,
    RevocationService,
    ScopePermissionRevocationAuthorizer,
)
from neurosphere_core.auth.scope import (
    InMemoryPolicyRepository,
    Permission,
    PolicyGrant,
    PolicyHead,
    PolicyRoleAssignment,
    PrincipalPolicy,
    PrincipalPseudonymizer,
    PseudonymKey,
    Role,
    ScopeDerivation,
    ScopeDerivationConfig,
    ScopeDeriver,
    permits,
    principal_document_id,
)
from neurosphere_core.cloud import CloudName, Settings
from neurosphere_core.errors import ForbiddenError
from neurosphere_core.scope import IdentityScope
from neurosphere_core.search import SearchRequest, SearchResult
from neurosphere_core.search.fixture import FixtureSearchIndex, documents_from_catalog
from pydantic import ValidationError

AUDIENCE = "api://neurosphere-test-api"
POLICY_VERSION = "2026.10.01-1"
T0 = 1_800_000_000.0
KEY_REFERENCE = "https://ns-test-kv.vault.azure.net/secrets/principal-pseudonym-key"
TENANTS: Mapping[str, str] = {
    "contoso": "0f1e2d3c-4b5a-4968-8776-a5b4c3d2e1f0",
    "fabrikam": "1a2b3c4d-5e6f-4a7b-8c9d-0e1f2a3b4c5d",
}
CUSTOMERS = tuple(TENANTS)
DOMAINS = ("finance", "operations")
ROLES = (
    Role.VIEWER,
    Role.ANALYST,
    Role.DOMAIN_STEWARD,
    Role.ADMIN,
    Role.SECURITY_AUDITOR,
)
REVOCATION_TTL = 60.0
PLATFORM_CHAIN = "platform"


class Who(NamedTuple):
    """A principal: one role in one domain of one customer (no role spans domains)."""

    customer: str
    domain: str
    role: Role

    @property
    def label(self) -> str:
        return f"{self.customer}.{self.domain}.{self.role.value}"

    @property
    def object_id(self) -> str:
        return str(uuid.uuid5(uuid.NAMESPACE_URL, f"neurosphere-negative-suite/{self.label}"))

    @property
    def domain_id(self) -> str:
        return domain_id(self.customer, self.domain)


ALL_PRINCIPALS: tuple[Who, ...] = tuple(
    Who(c, d, r) for c in CUSTOMERS for d in DOMAINS for r in ROLES
)


def domain_id(customer: str, domain: str, cloud: str = "commercial") -> str:
    return f"{cloud}:{customer}:catalog:domain:{domain}"


def item_id(customer: str, domain: str, n: int) -> str:
    return f"commercial:{customer}:catalog:agent:{domain}-triage-{n}"


ALL_DOMAIN_IDS: tuple[str, ...] = tuple(domain_id(c, d) for c in CUSTOMERS for d in DOMAINS)
ALL_ITEM_IDS: tuple[str, ...] = tuple(
    item_id(c, d, n) for c in CUSTOMERS for d in DOMAINS for n in (1, 2)
)


def catalog_entities() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for c in CUSTOMERS:
        for d in DOMAINS:
            out.append({"id": domain_id(c, d), "name": f"{d} domain triage"})
            for n in (1, 2):
                out.append(
                    {
                        "id": item_id(c, d, n),
                        "domain_id": domain_id(c, d),
                        "name": f"{d} triage assistant {n}",
                    }
                )
    return out


def item_domain(item: str) -> str:
    _cloud, customer, _source, _type, local = item.split(":")
    return domain_id(customer, local.split("-")[0])


class FakeClock:
    def __init__(self, now: float = T0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds

    def dt(self, offset: float = 0.0) -> datetime:
        return datetime.fromtimestamp(self.now + offset, UTC)


def at(offset_seconds: float) -> datetime:
    return datetime.fromtimestamp(T0, UTC) + timedelta(seconds=offset_seconds)


@cache
def dev_issuer(customer: str) -> DevIssuer:
    return DevIssuer(Settings(env="local"), tenant_id=TENANTS[customer], kid=f"dev-neg-{customer}")


@cache
def _unrelated_keys() -> Any:
    """Entra JWKS stand-in: an unrelated key, so only the trusted dev issuer validates."""
    return DevIssuer(
        Settings(env="local"), tenant_id=TENANTS["contoso"], kid="entra-stand-in"
    ).jwks()


class _StandInJwks:
    def __init__(self, url: str) -> None:
        self._url = url

    @property
    def url(self) -> str:
        return self._url

    async def fetch(self) -> Any:
        return _unrelated_keys()


def pseudonymizer() -> PrincipalPseudonymizer:
    return PrincipalPseudonymizer(PseudonymKey(bytes(range(32)), reference=KEY_REFERENCE))


def principal_id_for(who: Who) -> str:
    return pseudonymizer().principal_id(
        cloud=CloudName.COMMERCIAL,
        customer_id=who.customer,
        tenant_id=TENANTS[who.customer],
        object_id=who.object_id,
        kind="user",
    )


def make_grant(
    resource_id: str, *permissions: str, expires_in: float = 1800, grant_id: str | None = None
) -> PolicyGrant:
    return PolicyGrant.model_validate(
        {
            "grant_id": grant_id or f"g-{resource_id.rsplit(':', 1)[-1]}",
            "resource_id": resource_id,
            "permissions": list(permissions) or ["read"],
            "expires_at": at(expires_in),
            "reason": "incident review INC-42",
        }
    )


def principal_policy(who: Who, grants: Iterable[PolicyGrant] = ()) -> PrincipalPolicy:
    pid = principal_id_for(who)
    privileged = who.role in (Role.ADMIN, Role.SECURITY_AUDITOR)
    return PrincipalPolicy(
        id=principal_document_id(pid),
        customer_id=who.customer,
        principal_id=pid,
        domain_memberships=(who.domain_id,),
        role_assignments=(
            PolicyRoleAssignment(
                assignment_id=f"ra-{who.label}",
                role=who.role,
                domain_ids=(who.domain_id,),
                expires_at=at(7 * 24 * 3600) if privileged else None,
            ),
        ),
        grants=tuple(grants),
    )


def run[T](coro: Coroutine[Any, Any, T]) -> T:
    return asyncio.run(coro)


# ----------------------------------------------------------------------------------- audit


def chain_for(customer: str, domain: str | None) -> str:
    return f"{customer}.{domain or PLATFORM_CHAIN}"


def domain_short(target_domain_id: str | None) -> str | None:
    return target_domain_id.rsplit(":", 1)[-1] if target_domain_id else None


class AccessAudit:
    """Writes allow/denied access records with item 4's builders. Actor and scope hash come
    from the server-derived scope (``AuditContext.from_scope``), never from request input."""

    def __init__(self, repository: AuditRepository) -> None:
        self.repository = repository
        self._n = 0

    def _ctx(self, scope: IdentityScope, operation: str) -> AuditContext:
        self._n += 1
        return AuditContext.from_scope(
            scope, correlation_id=f"neg-{self._n:06d}", operation=operation, channel="rest"
        )

    @staticmethod
    def _chain(scope: IdentityScope, domain: str | None) -> str:
        return chain_for(scope.customer_id, domain_short(domain))

    async def allow(
        self, scope: IdentityScope, operation: str, *, target: str | None, domain: str | None
    ) -> None:
        subject = make_subject(target or domain or _platform_target(scope), "access_target")
        await self.repository.append(
            self._chain(scope, domain), build_allowed(self._ctx(scope, operation), subject)
        )

    async def deny(
        self,
        scope: IdentityScope,
        operation: str,
        reason: str,
        *,
        target: str | None,
        domain: str | None,
        code: DenialCode = "forbidden",
    ) -> None:
        subject = make_subject(target, "access_target") if target else None
        await self.repository.append(
            self._chain(scope, domain),
            build_denied(self._ctx(scope, operation), code=code, reason=reason, subject=subject),
        )

    async def all_records(self, customers: Iterable[str] = CUSTOMERS) -> list[Any]:
        out: list[Any] = []
        for customer in customers:
            for domain in (*DOMAINS, PLATFORM_CHAIN):
                out.extend(await self.repository.read_range(chain_for(customer, domain), limit=500))
        return out


def _platform_target(scope: IdentityScope) -> str:
    return f"{scope.cloud}:{scope.customer_id}:catalog:service:platform"


@dataclass
class RouteDenialRecorder:
    """Item 3's ``DenialRecorder`` hook wired to the access audit (item 4 builders)."""

    audit: AccessAudit
    attempts: list[DeniedAttempt] = field(default_factory=list)

    async def record_denial(self, attempt: DeniedAttempt) -> None:
        self.attempts.append(attempt)
        await self.audit.deny(
            attempt.scope,
            attempt.permission,
            attempt.reason,
            target=attempt.resource_id or attempt.domain_id,
            domain=attempt.domain_id,
        )


# ------------------------------------------------------------------------------ data layer


def in_scope_items(scope: IdentityScope, now: datetime) -> list[str]:
    """Catalog item ids ``scope`` may read: the one shared visibility rule (REST, cache)."""
    return [
        i
        for i in ALL_ITEM_IDS
        if permits(scope, Permission.DATA_READ, now=now, domain_id=item_domain(i), resource_id=i)
    ]


class ScopedExporter:
    """Export function: authorizes ``data.export`` per target against the passed scope."""

    def __init__(self, clock: FakeClock) -> None:
        self._clock = clock

    def export(
        self, scope: IdentityScope, *, domain_id: str | None = None, resource_id: str | None = None
    ) -> list[str]:
        now = self._clock.dt()
        if domain_id is None and resource_id is None:
            raise ForbiddenError("export needs a target", reason="export_target_required")
        if not permits(
            scope, Permission.DATA_EXPORT, now=now, domain_id=domain_id, resource_id=resource_id
        ):
            raise ForbiddenError("export outside scope", reason="export_out_of_scope")
        return [
            i
            for i in ALL_ITEM_IDS
            if (domain_id is not None and item_domain(i) == domain_id) or i == resource_id
        ]


class ScopeKeyedCache:
    """Cache of scope-filtered catalog views, keyed by ``scope_cache_key`` of the same scope."""

    def __init__(self, clock: FakeClock) -> None:
        self._clock = clock
        self.entries: dict[str, list[str]] = {}
        self._principal_keys: dict[str, set[str]] = {}
        self.loads = 0

    def get_view(self, scope: IdentityScope, namespace: str = "catalog") -> list[str]:
        key = scope_cache_key(scope, namespace=namespace)
        if key not in self.entries:
            self.loads += 1
            self.entries[key] = in_scope_items(scope, self._clock.dt())
            pid = scope.to_contract().principal.principal_id.root
            self._principal_keys.setdefault(pid, set()).add(key)
        return list(self.entries[key])

    def invalidate_principal(self, principal_id: str) -> int:
        keys = self._principal_keys.pop(principal_id, set())
        for k in keys:
            self.entries.pop(k, None)
        return len(keys)


@dataclass
class PushSession:
    principal_id: str
    domain_id: str


class FakePushRegistry:
    """Fake PRP-18 gateway: a ``PushSessionRegistry`` plus scope-checked ``connect``."""

    def __init__(self, clock: FakeClock, *, fail: bool = False) -> None:
        self._clock = clock
        self.sessions: list[PushSession] = []
        self.closed_for: list[str] = []
        self.fail = fail

    def connect(self, scope: IdentityScope, domain_id: str) -> PushSession:
        if not permits(scope, Permission.DATA_READ, now=self._clock.dt(), domain_id=domain_id):
            raise ForbiddenError("push subscription outside scope", reason="push_out_of_scope")
        session = PushSession(scope.to_contract().principal.principal_id.root, domain_id)
        self.sessions.append(session)
        return session

    def deliver(self, event_domain_id: str) -> list[str]:
        """Principal ids that receive an event in ``event_domain_id``."""
        return [s.principal_id for s in self.sessions if s.domain_id == event_domain_id]

    async def close_for_principal(self, principal_id: str) -> int:
        self.closed_for.append(principal_id)
        if self.fail:
            raise RuntimeError("push registry unavailable")
        before = len(self.sessions)
        self.sessions = [s for s in self.sessions if s.principal_id != principal_id]
        return before - len(self.sessions)


SEARCH_BUDGET = Budget(timeout_ms=5000, limit=50, max_depth=0)


class SearchGateway:
    """Reference caller of ``AuthorizedSearch``: passes the server-derived scope, never a
    caller-supplied one, and audits the decision. Filters come from untrusted input and are
    validated by the closed ``SearchRequest`` schema (unknown fields are refused)."""

    def __init__(self, index: FixtureSearchIndex, audit: AccessAudit) -> None:
        self._index = index
        self._audit = audit

    async def search(
        self, scope: IdentityScope, term: str, raw_filters: Mapping[str, Any] | None = None
    ) -> tuple[SearchResult, str]:
        """Returns ``(result, decision)``; decision is ``allow`` or the denial reason. A refused
        request raises ``ValidationError`` after a denied record is written."""
        try:
            request = SearchRequest.model_validate(
                {
                    "term": term,
                    "filters": dict(raw_filters or {}),
                    "budget": SEARCH_BUDGET.model_dump(),
                }
            )
        except ValidationError:
            await self._audit.deny(
                scope,
                "data.read",
                "filter_widening_refused",
                target=None,
                domain=None,
                code="invalid_schema",
            )
            raise
        contract = scope.to_contract()
        visible = set(scope.allowed_domains)
        granted = {
            g.resource_id.root for g in contract.allowed_resources if "read" in g.permissions
        }
        reachable = visible | {item_domain(g) for g in granted}
        requested = request.filters.domain_ids
        decision = "allow"
        if not visible and not granted:
            decision = "permission_missing"
        elif requested and not set(requested) <= reachable:
            decision = "filter_out_of_scope"
        result = await self._index.search(contract, request)
        if decision == "allow":
            await self._audit.allow(scope, "data.read", target=None, domain=None)
        else:
            await self._audit.deny(scope, "data.read", decision, target=None, domain=None)
        return result, decision


class CollectingRevocationAuditor:
    def __init__(self) -> None:
        self.events: list[RevocationAuditEvent] = []

    async def record(self, event: RevocationAuditEvent) -> None:
        self.events.append(event)


# -------------------------------------------------------------------------------- HTTP app


def _data_router(dep: "Deployment") -> APIRouter:
    router = APIRouter()
    audit = dep.audit
    clock = dep.clock

    domain_dep = require(Permission.DATA_READ, domain_from_path("domain_id"))
    resource_dep = require(Permission.DATA_READ, resource_from_path("resource_id"))
    read_dep = require(Permission.DATA_READ)
    export_dep = require(Permission.DATA_EXPORT)
    config_dep = require(Permission.CONFIG_MANAGE)

    @router.get("/domains/{domain_id}/items")
    async def domain_items(
        domain_id: str, scope: Annotated[IdentityScope, Depends(domain_dep)]
    ) -> dict[str, Any]:
        items = [i for i in in_scope_items(scope, clock.dt()) if item_domain(i) == domain_id]
        await audit.allow(scope, "data.read", target=domain_id, domain=domain_id)
        return {"items": items}

    @router.get("/resources/{resource_id}")
    async def resource(
        resource_id: str, scope: Annotated[IdentityScope, Depends(resource_dep)]
    ) -> dict[str, Any]:
        await audit.allow(scope, "data.read", target=resource_id, domain=None)
        return {"items": [resource_id]}

    @router.get("/items")
    async def list_items(
        scope: Annotated[IdentityScope, Depends(read_dep)],
        domain_id: Annotated[str | None, Query()] = None,
        x_domain_id: Annotated[str | None, Header()] = None,
        x_customer_id: Annotated[str | None, Header()] = None,
    ) -> dict[str, Any]:
        # domain_id / headers are deliberately unused: scope is the only authority.
        items = in_scope_items(scope, clock.dt())
        await audit.allow(scope, "data.read", target=None, domain=None)
        return {"items": items}

    @router.post("/query")
    async def query(
        scope: Annotated[IdentityScope, Depends(read_dep)],
        body: Annotated[dict[str, Any] | None, Body()] = None,
    ) -> dict[str, Any]:
        items = in_scope_items(scope, clock.dt())
        await audit.allow(scope, "data.read", target=None, domain=None)
        return {"items": items}

    @router.post("/export")
    async def export(
        scope: Annotated[IdentityScope, Depends(export_dep)],
        body: Annotated[dict[str, Any] | None, Body()] = None,
    ) -> dict[str, Any]:
        raw_domain = (body or {}).get("domain_id")
        raw_resource = (body or {}).get("resource_id")
        domain = raw_domain if isinstance(raw_domain, str) else None
        resource_id = raw_resource if isinstance(raw_resource, str) else None
        try:
            rows = dep.exporter.export(scope, domain_id=domain, resource_id=resource_id)
        except ForbiddenError as exc:
            await audit.deny(
                scope,
                "data.export",
                exc.reason or "forbidden",
                target=resource_id or domain,
                domain=domain,
            )
            raise
        await audit.allow(scope, "data.export", target=resource_id or domain, domain=domain)
        return {"items": rows}

    @router.get("/config")
    async def config(scope: Annotated[IdentityScope, Depends(config_dep)]) -> dict[str, Any]:
        await audit.allow(scope, "config.manage", target=None, domain=None)
        return {"config": "ok"}

    return router


# ------------------------------------------------------------------------------ deployment


@dataclass
class Deployment:
    customer: str
    clock: FakeClock
    repo: InMemoryPolicyRepository
    revocation_store: InMemoryRevocationStore
    checker: CachedRevocationChecker
    deriver: ScopeDeriver
    validator: JwtValidator
    audit_store: InMemoryAuditStore
    audit_repo: AuditRepository
    audit: AccessAudit
    recorder: RouteDenialRecorder
    exporter: ScopedExporter
    search: SearchGateway
    cache: ScopeKeyedCache
    push: FakePushRegistry
    hooks: RevocationHookRegistry
    revocation_auditor: CollectingRevocationAuditor
    service: RevocationService
    app: FastAPI = field(init=False)
    client: TestClient = field(init=False)

    def token(self, who: Who, **extra: Any) -> str:
        return dev_issuer(who.customer).mint(
            audience=AUDIENCE, object_id=who.object_id, now=self.clock.now, extra=extra or None
        )

    def bearer(self, who: Who, **extra: Any) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token(who, **extra)}"}

    async def derive_token(self, token: str) -> ScopeDerivation:
        claims = await self.validator.authenticate(f"Bearer {token}")
        return await self.deriver.derive(claims)

    async def derive(self, who: Who) -> ScopeDerivation:
        return await self.derive_token(self.token(who))

    def scope(self, who: Who) -> IdentityScope:
        return run(self.derive(who)).scope

    def revoke(self, actor: Who, target: Who, *, hooks: bool = True) -> RevocationOutcome:
        """Admin revoke through item 5's service. ``hooks=False`` models a revocation performed
        on ANOTHER replica: the store is written but this replica's caches are not invalidated."""
        service = self.service if hooks else self._remote_service()
        return run(service.revoke(self.scope(actor), principal_id_for(target), reason="test_case"))

    def _remote_service(self) -> RevocationService:
        return RevocationService(
            store=self.revocation_store,
            authorizer=ScopePermissionRevocationAuthorizer(clock=self.clock),
            auditor=self.revocation_auditor,
            hooks=RevocationHookRegistry(),
            ttl_seconds=REVOCATION_TTL,
            clock=self.clock,
        )

    def audit_records(self) -> list[Any]:
        return run(self.audit.all_records([self.customer]))


@dataclass
class World:
    clock: FakeClock
    deployments: dict[str, Deployment]
    search_index: FixtureSearchIndex

    def __getitem__(self, customer: str) -> Deployment:
        return self.deployments[customer]


def _chain_domain(scope: IdentityScope, chain_id: str) -> str | None:
    name = chain_id.partition(".")[2]
    return domain_id(scope.customer_id, name) if name in (*DOMAINS, PLATFORM_CHAIN) else None


def _build_deployment(
    customer: str,
    clock: FakeClock,
    index: FixtureSearchIndex,
    grants: Mapping[Who, tuple[PolicyGrant, ...]],
    policy_version: str,
) -> Deployment:
    repo = InMemoryPolicyRepository()
    repo.put_head(PolicyHead(customer_id=customer, policy_version=policy_version))
    for who in ALL_PRINCIPALS:
        if who.customer == customer:
            repo.put_principal(principal_policy(who, grants.get(who, ())))
    store = InMemoryRevocationStore(clock=clock)
    checker = CachedRevocationChecker(store, ttl_seconds=REVOCATION_TTL, clock=clock)
    cfg = ScopeDerivationConfig(
        cloud=CloudName.COMMERCIAL, tenant_id=TENANTS[customer], customer_id=customer
    )
    deriver = ScopeDeriver(
        cfg,
        policy_repository=repo,
        pseudonymizer=pseudonymizer(),
        revocation_checker=checker,
        clock=clock,
    )
    jwt_config = JwtConfig(
        env="local",
        cloud=CloudName.COMMERCIAL,
        tenant_id=TENANTS[customer],
        audiences=(AUDIENCE,),
        dev_issuer=dev_issuer(customer).trust(),
    )
    fetcher = _StandInJwks(entra_jwks_uri(CloudName.COMMERCIAL, TENANTS[customer]))
    jwks = JwksCache(fetcher, clock=clock, ttl_seconds=3600, min_refresh_interval_seconds=300)
    validator = JwtValidator(jwt_config, jwks, clock=clock)

    audit_store = InMemoryAuditStore()
    audit_repo = AuditRepository(audit_store)
    audit = AccessAudit(audit_repo)
    recorder = RouteDenialRecorder(audit)
    cache = ScopeKeyedCache(clock)
    push = FakePushRegistry(clock)
    hooks = RevocationHookRegistry()
    hooks.register_cache_invalidator("revocation-checker", checker.invalidate_principal)
    hooks.register_cache_invalidator("scope-deriver", deriver.invalidate_principal)
    hooks.register_cache_invalidator("scope-cache", cache.invalidate_principal)
    hooks.register_push_registry("push", push)
    rev_auditor = CollectingRevocationAuditor()
    service = RevocationService(
        store=store,
        authorizer=ScopePermissionRevocationAuthorizer(clock=clock),
        auditor=rev_auditor,
        hooks=hooks,
        ttl_seconds=REVOCATION_TTL,
        clock=clock,
    )
    dep = Deployment(
        customer=customer,
        clock=clock,
        repo=repo,
        revocation_store=store,
        checker=checker,
        deriver=deriver,
        validator=validator,
        audit_store=audit_store,
        audit_repo=audit_repo,
        audit=audit,
        recorder=recorder,
        exporter=ScopedExporter(clock),
        search=SearchGateway(index, audit),
        cache=cache,
        push=push,
        hooks=hooks,
        revocation_auditor=rev_auditor,
        service=service,
    )
    audit_router = build_audit_router(
        require_permission=audit_require_permission(chain_domain=_chain_domain)
    )
    dep.app = create_app(
        Settings(env="local"),
        extra_routers={"/d": _data_router(dep), "/audit": audit_router},
    )
    dep.app.state.audit_repository = audit_repo
    configure_authz(
        dep.app,
        authenticator=validator,
        scope_source=deriver,
        clock=clock,
        denial_recorder=recorder,
    )
    dep.client = TestClient(dep.app, raise_server_exceptions=False)
    return dep


def build_world(
    *,
    grants: Mapping[Who, tuple[PolicyGrant, ...]] | None = None,
    policy_version: str = POLICY_VERSION,
) -> World:
    clock = FakeClock()
    index = FixtureSearchIndex(documents_from_catalog(catalog_entities()))
    deployments = {
        c: _build_deployment(c, clock, index, grants or {}, policy_version) for c in CUSTOMERS
    }
    return World(clock=clock, deployments=deployments, search_index=index)
