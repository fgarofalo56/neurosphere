"""Shared harness for item 3 tests: dev-issuer tokens (NS_ENV=local), in-memory policy store,
fake clock, and an app built by the PRP-05 factory with ``configure_authz`` applied.

No network, no real tenant, no credential: the dev issuer's key lives in memory (item 1, C3).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from functools import cache
from typing import Annotated, Any

from fastapi import APIRouter, Body, Depends, FastAPI
from fastapi.testclient import TestClient
from neurosphere_api.app import create_app
from neurosphere_api.authz import (
    DenialRecorder,
    DeniedAttempt,
    configure_authz,
    domain_from_path,
    require,
    resource_from_path,
)
from neurosphere_core.auth.jwt import DevIssuer, JwksCache, JwtConfig, JwtValidator, entra_jwks_uri
from neurosphere_core.auth.scope import (
    InMemoryPolicyRepository,
    Permission,
    PolicyGrant,
    PolicyHead,
    PolicyRoleAssignment,
    PrincipalPolicy,
    PrincipalPseudonymizer,
    PseudonymKey,
    RevocationChecker,
    Role,
    ScopeDerivationConfig,
    ScopeDeriver,
    principal_document_id,
)
from neurosphere_core.cloud import CloudName, Settings
from neurosphere_core.scope import IdentityScope

TENANT = "0f1e2d3c-4b5a-4968-8776-a5b4c3d2e1f0"
AUDIENCE = "api://neurosphere-test-api"
CUSTOMER = "contoso"
POLICY_VERSION = "2026.10.01-1"
T0 = 1_800_000_000.0
KEY_REFERENCE = "https://ns-test-kv.vault.azure.net/secrets/principal-pseudonym-key"

ALICE = "6c1d2e3f-4a5b-4c6d-8e7f-90a1b2c3d4e5"
BOB = "7d2e3f4a-5b6c-4d7e-8f90-a1b2c3d4e5f6"
CAROL = "8e3f4a5b-6c7d-4e8f-90a1-b2c3d4e5f6a7"
NOBODY = "9f4a5b6c-7d8e-4f90-a1b2-c3d4e5f6a7b8"

FINANCE = "commercial:contoso:catalog:domain:finance"
OPERATIONS = "commercial:contoso:catalog:domain:operations"
HR = "commercial:contoso:catalog:domain:hr"
OTHER_CUSTOMER_FINANCE = "commercial:fabrikam:catalog:domain:finance"
GOV_FINANCE = "government:contoso:catalog:domain:finance"
AGENT = "commercial:contoso:foundry:agent:support-bot"
OTHER_AGENT = "commercial:contoso:foundry:agent:hr-bot"


class FakeClock:
    def __init__(self, now: float = T0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class StandInJwksFetcher:
    """Entra JWKS stand-in holding one unrelated local key; no test token is signed with it, so
    only the trusted dev issuer's kid validates and any other kid is ``unknown_kid`` (401)."""

    def __init__(self, url: str) -> None:
        self._url = url
        self.calls = 0

    @property
    def url(self) -> str:
        return self._url

    async def fetch(self) -> Any:
        self.calls += 1
        return dev_issuer("entra-stand-in").jwks()


def at(offset_seconds: float) -> datetime:
    return datetime.fromtimestamp(T0, UTC) + timedelta(seconds=offset_seconds)


@cache
def dev_issuer(kid: str = "dev-authz-tests") -> DevIssuer:
    return DevIssuer(Settings(env="local"), tenant_id=TENANT, kid=kid)


def pseudonymizer() -> PrincipalPseudonymizer:
    return PrincipalPseudonymizer(PseudonymKey(bytes(range(32)), reference=KEY_REFERENCE))


def principal_id_for(object_id: str) -> str:
    return pseudonymizer().principal_id(
        cloud=CloudName.COMMERCIAL,
        customer_id=CUSTOMER,
        tenant_id=TENANT,
        object_id=object_id,
        kind="user",
    )


def role(r: Role, *domains: str, expires_in: float | None = None) -> PolicyRoleAssignment:
    if expires_in is None and r in (Role.ADMIN, Role.SECURITY_AUDITOR):
        expires_in = 7 * 24 * 3600  # privileged roles must be time-bound (C7)
    return PolicyRoleAssignment(
        assignment_id=f"ra-{r.value}-{len(domains)}",
        role=r,
        domain_ids=domains,
        expires_at=None if expires_in is None else at(expires_in),
    )


def grant(resource_id: str, *permissions: str, expires_in: float = 1800) -> PolicyGrant:
    return PolicyGrant.model_validate(
        {
            "grant_id": f"g-{resource_id.rsplit(':', 1)[-1]}",
            "resource_id": resource_id,
            "permissions": list(permissions),
            "expires_at": at(expires_in),
            "reason": "incident review INC-42",
        }
    )


def policy(
    object_id: str,
    *roles: PolicyRoleAssignment,
    grants: tuple[PolicyGrant, ...] = (),
    memberships: tuple[str, ...] = (FINANCE, OPERATIONS, HR),
) -> PrincipalPolicy:
    pid = principal_id_for(object_id)
    return PrincipalPolicy(
        id=principal_document_id(pid),
        customer_id=CUSTOMER,
        principal_id=pid,
        domain_memberships=memberships,
        role_assignments=roles,
        grants=grants,
    )


class RecordingDenials:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.attempts: list[DeniedAttempt] = []

    async def record_denial(self, attempt: DeniedAttempt) -> None:
        self.attempts.append(attempt)
        if self.error is not None:
            raise self.error


def _scope_body(scope: IdentityScope) -> dict[str, Any]:
    return {
        "scope_hash": scope.scope_hash,
        "customer_id": scope.customer_id,
        "allowed_domains": list(scope.allowed_domains),
    }


DataRead = Annotated[IdentityScope, Depends(require(Permission.DATA_READ))]
DomainRead = Annotated[
    IdentityScope, Depends(require(Permission.DATA_READ, domain_from_path("domain_id")))
]
ResourceRead = Annotated[
    IdentityScope, Depends(require(Permission.DATA_READ, resource_from_path("resource_id")))
]
ConfigManage = Annotated[IdentityScope, Depends(require(Permission.CONFIG_MANAGE))]


def build_router() -> APIRouter:
    """Routes exercising each ``require`` shape. Every route declares a permission."""
    router = APIRouter()

    @router.api_route("/whoami", methods=["GET", "POST"])
    async def whoami(
        scope: DataRead, body: Annotated[dict[str, Any] | None, Body()] = None
    ) -> dict[str, Any]:
        return _scope_body(scope)

    @router.get("/data")
    async def data(scope: DataRead) -> dict[str, Any]:
        return _scope_body(scope)

    @router.get("/domains/{domain_id}/data")
    async def domain_data(domain_id: str, scope: DomainRead) -> dict[str, Any]:
        return _scope_body(scope)

    @router.get("/resources/{resource_id}")
    async def resource(resource_id: str, scope: ResourceRead) -> dict[str, Any]:
        return _scope_body(scope)

    @router.post("/config")
    async def config(scope: ConfigManage) -> dict[str, Any]:
        return _scope_body(scope)

    @router.get("/config")
    async def read_config(scope: ConfigManage) -> dict[str, Any]:
        return _scope_body(scope)

    return router


@dataclass
class Harness:
    app: FastAPI
    client: TestClient
    clock: FakeClock
    repo: InMemoryPolicyRepository
    deriver: ScopeDeriver
    validator: JwtValidator

    def token(self, object_id: str, **extra: Any) -> str:
        return dev_issuer().mint(
            audience=AUDIENCE, object_id=object_id, now=self.clock.now, extra=extra or None
        )

    def auth(self, object_id: str, **extra: Any) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token(object_id, **extra)}"}


def make_validator(clock: FakeClock) -> JwtValidator:
    config = JwtConfig(
        env="local",
        cloud=CloudName.COMMERCIAL,
        tenant_id=TENANT,
        audiences=(AUDIENCE,),
        dev_issuer=dev_issuer().trust(),
    )
    fetcher = StandInJwksFetcher(entra_jwks_uri(CloudName.COMMERCIAL, TENANT))
    jwks = JwksCache(fetcher, clock=clock, ttl_seconds=3600, min_refresh_interval_seconds=300)
    return JwtValidator(config, jwks, clock=clock)


def make_deriver(
    repo: InMemoryPolicyRepository,
    clock: FakeClock,
    *,
    revocation_checker: RevocationChecker | None = None,
    **config: Any,
) -> ScopeDeriver:
    cfg = ScopeDerivationConfig(
        cloud=CloudName.COMMERCIAL, tenant_id=TENANT, customer_id=CUSTOMER, **config
    )
    return ScopeDeriver(
        cfg,
        policy_repository=repo,
        pseudonymizer=pseudonymizer(),
        revocation_checker=revocation_checker,
        clock=clock,
    )


def make_app(*, routers: dict[str, APIRouter] | None = None) -> FastAPI:
    """PRP-05 factory app (health router included) plus ``routers`` (default: ``/t`` routes)."""
    return create_app(
        Settings(env="local"),
        extra_routers=routers if routers is not None else {"/t": build_router()},
    )


def harness(
    *policies: PrincipalPolicy,
    routers: dict[str, APIRouter] | None = None,
    denials: DenialRecorder | None = None,
    revocation_checker: RevocationChecker | None = None,
    policy_version: str | None = POLICY_VERSION,
    **deriver_config: Any,
) -> Harness:
    clock = FakeClock()
    repo = InMemoryPolicyRepository()
    if policy_version is not None:
        repo.put_head(PolicyHead(customer_id=CUSTOMER, policy_version=policy_version))
    for p in policies:
        repo.put_principal(p)
    deriver = make_deriver(repo, clock, revocation_checker=revocation_checker, **deriver_config)
    validator = make_validator(clock)
    app = make_app(routers=routers)
    configure_authz(
        app, authenticator=validator, scope_source=deriver, clock=clock, denial_recorder=denials
    )
    return Harness(
        app=app,
        client=TestClient(app, raise_server_exceptions=False),
        clock=clock,
        repo=repo,
        deriver=deriver,
        validator=validator,
    )
