"""ABAC suite for the Entra claim role mapping (PRP-138 item 7).

Everything below runs against the COMPOSED application: ``create_app`` + ``compose_app`` with the
production builders, ``NS_AUTH_ROLE_MAPPINGS`` read from the environment by the authz builder, and
only these test seams (``CompositionOverrides``, test code only): the token validator (trusting a
stand-in Entra signing key and the local test issuer), the in-memory policy and revocation stores,
an in-memory admin config store (domain registry) and an in-memory audit repository published
right after the authz builder (the data, planes and gateway builders need Cosmos and are stubbed
``ok``). Tokens of issuer kind ``entra`` are signed by the stand-in key with the cloud's real Entra
issuer string; tokens of kind ``dev`` come from the suite's local test issuer (``world.py``).

=========================================  ================================================
Dimension                                  Expected
=========================================  ================================================
first admin, empty policy store/registry   200 on the admin status route, nothing stored
``domains: all``                           control + every active registry domain, expiry =
                                           token ``exp``; registry changes follow the cache
mapped admin, deployment-scoped routes     never 401/403, no denial
no mapping configured                      claims change nothing: 403, denial recorded,
                                           ``mapping_configured: false``
unmapped value, no ``roles``, other        nothing mapped (403) or refused (401); never
tenant/audience, local issuer outside      mapped
local, app-only, no ``scp``, overage
groups entry                               applied from the ``groups`` claim
no bypass                                  exactly the ``admin`` permission set; 403 on
                                           ``action.approve``, ``audit.read`` and on its own
                                           policy document
clouds                                     a Commercial mapping never maps a Government
                                           token and the reverse
time bound, revocation                     expiry = token ``exp``; a new token without the
                                           role maps nothing; revocation wins before mapping
audit                                      one ``identity.claim_role_applied`` per token,
                                           metadata only; write failure is 503
read views                                 role-mapping view (control domain admins only),
                                           ``/me/access`` source ``entra_app_role``
startup refusals                           503 ``authz_unconfigured`` + readiness reason
=========================================  ================================================
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import urllib.request
import uuid
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import cache
from typing import Any, Final

import httpx
import jwt
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from neurosphere_api.app import create_app
from neurosphere_api.authz import claim_mapping_stats
from neurosphere_api.runtime import ComponentRegistry, CompositionOverrides, compose_app
from neurosphere_api.runtime.builders import (
    AUDIT_REPOSITORY,
    BuildContext,
    BuilderSpec,
    default_builders,
)
from neurosphere_api.runtime.pseudonym import local_dev_pseudonym_key
from neurosphere_contracts.admin.v1.domain_definition import DomainDefinition
from neurosphere_core.admin import InMemoryAdminConfigRepository
from neurosphere_core.admin.platform import DomainAdmin
from neurosphere_core.audit import AuditRepository, InMemoryAuditStore
from neurosphere_core.auth.jwt import (
    DevIssuer,
    JwksCache,
    JwtConfig,
    JwtValidator,
    VerifiedClaims,
    entra_jwks_uri,
)
from neurosphere_core.auth.jwt.config import entra_issuers
from neurosphere_core.auth.revocation import InMemoryRevocationStore
from neurosphere_core.auth.scope import (
    ClaimGrant,
    InMemoryPolicyRepository,
    Permission,
    PolicyHead,
    PolicyRoleAssignment,
    PrincipalPolicy,
    PrincipalPseudonymizer,
    Role,
    ScopeDerivation,
    ScopeDerivationConfig,
    ScopeDeriver,
    customer_control_domain_id,
    parse_claim_role_mapping,
    permits,
    principal_document_id,
    role_permissions,
)
from neurosphere_core.auth.scope.revocation_hook import NoRevocationCheck
from neurosphere_core.cloud import CloudName, Settings
from neurosphere_core.errors import UnauthorizedError
from neurosphere_core.scope import IdentityScope

from .test_deployment_scope import ROUTES, Route
from .world import AUDIENCE, POLICY_VERSION, TENANTS, FakeClock, dev_issuer, domain_id

CUSTOMER: Final = "contoso"
TENANT: Final = TENANTS[CUSTOMER]
OTHER_TENANT: Final = TENANTS["fabrikam"]
SECOND_AUDIENCE: Final = "api://neurosphere-second-api"
SCP: Final = "access_as_user"
LIFETIME: Final = 3600

CONTROL: Final = customer_control_domain_id("commercial", CUSTOMER)
GOV_CONTROL: Final = customer_control_domain_id("government", CUSTOMER)
FIN: Final = domain_id(CUSTOMER, "finance")
OPS: Final = domain_id(CUSTOMER, "operations")
HR: Final = domain_id(CUSTOMER, "hr")
SALES: Final = domain_id(CUSTOMER, "sales")
GOV_FIN: Final = domain_id(CUSTOMER, "finance", "government")

#: Entra group object id mapped by the groups entry (configuration, never in an audit record).
GROUP: Final = "3f2504e0-4f89-41d3-9a0c-0305e82c3301"
#: A distinctive app role value: proves the audit record never carries the claim value.
ROLE_VALUE: Final = "NeuroSphere.Owner"

MAPPED_OID: Final = "b1c2d3e4-0000-4000-8000-000000000138"
SECOND_OID: Final = "b1c2d3e4-0000-4000-8000-000000001138"
STORED_ADMIN_OID: Final = "b1c2d3e4-0000-4000-8000-00000000a138"
DOMAIN_ADMIN_OID: Final = "b1c2d3e4-0000-4000-8000-00000000d138"
SELF_OID: Final = "b1c2d3e4-0000-4000-8000-00000000e138"

STATUS: Final = "/api/v1/admin/system/status"
ME_ACCESS: Final = "/api/v1/me/access"
ME_DOMAINS: Final = "/api/v1/me/domains"
ROLE_MAPPING: Final = "/api/v1/admin/identity/role-mapping"
PRINCIPALS: Final = "/api/v1/admin/identity/principals"
CLAIM_ROLE_APPLIED: Final = "identity.claim_role_applied"
GUID: Final = re.compile(
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
)

_PREFIXES: Final = (
    "NS_AUTH_",
    "NS_STORE_",
    "NS_CORS_",
    "NS_COSMOS_",
    "NS_REVOCATION_",
    "NS_COPILOT_",
)
_NAMES: Final = (
    "NS_CLOUD",
    "NS_ENV",
    "NS_INGEST_PRODUCERS_FILE",
    "NS_SCAN_ENABLED",
    "NS_MCP_RESOURCE_SERVER_URL",
)


# ----------------------------------------------------------------------------- mapping JSON


def entry(**values: Any) -> dict[str, Any]:
    return {
        "id": "ns-admins",
        "claim": "roles",
        "value": "admin",
        "role": "admin",
        "domains": "all",
        "customer_control": True,
        **values,
    }


GROUP_ENTRY: Final = entry(
    id="finance-analysts", claim="groups", value=GROUP, role="analyst", domains=[FIN],
    customer_control=False,
)  # fmt: skip


def mapping_json(
    *entries: dict[str, Any], tenant_id: str = TENANT, audience: str = AUDIENCE
) -> str:
    return json.dumps(
        {"tenant_id": tenant_id, "audience": audience, "entries": list(entries) or [entry()]}
    )


# ----------------------------------------------------------------------------- tokens


@cache
def entra_signer() -> DevIssuer:
    """Stand-in for the tenant's Entra signing key (served as the Entra JWKS, test only)."""
    return DevIssuer(Settings(env="local"), tenant_id=TENANT, kid="entra-stand-in-prp138")


class _EntraJwks:
    def __init__(self, url: str) -> None:
        self._url = url

    @property
    def url(self) -> str:
        return self._url

    async def fetch(self) -> Any:
        return entra_signer().jwks()


def v2_issuer(cloud: CloudName, tenant: str) -> str:
    return next(iss for iss, ver in entra_issuers(cloud, tenant).items() if ver == "2.0")


def pid(object_id: str, cloud: CloudName = CloudName.COMMERCIAL) -> str:
    return PrincipalPseudonymizer(local_dev_pseudonym_key()).principal_id(
        cloud=cloud, customer_id=CUSTOMER, tenant_id=TENANT, object_id=object_id, kind="user"
    )


# ----------------------------------------------------------------------------- composition


def _stub(name: str, components: Sequence[str]) -> BuilderSpec:
    owned = tuple(components)

    def build(ctx: BuildContext) -> None:
        for component in owned:
            ctx.ok(component)

    return BuilderSpec(f"stub-{name}", owned, build)


def _publish_audit(audit: AuditRepository) -> BuilderSpec:
    """Stands in for the data builder's ``AUDIT_REPOSITORY`` (the data builder needs Cosmos)."""

    def build(ctx: BuildContext) -> None:
        ctx.publish(AUDIT_REPOSITORY, audit)

    return BuilderSpec("audit-repository", (), build)


def _builders(audit: AuditRepository) -> tuple[BuilderSpec, ...]:
    out: list[BuilderSpec] = []
    for spec in default_builders():
        if spec.name in ("data", "planes", "gateway"):
            out.append(_stub(spec.name, spec.components))
        else:
            out.append(spec)
        if spec.name == "authz":
            out.append(_publish_audit(audit))
    return tuple(out)


@dataclass
class Stack:
    """One composed deployment and the in-memory stores behind it."""

    app: FastAPI
    registry: ComponentRegistry
    client: TestClient
    clock: FakeClock
    cloud: CloudName
    repo: InMemoryPolicyRepository
    audit_store: InMemoryAuditStore
    audit: AuditRepository
    admin_config: InMemoryAdminConfigRepository
    validator: JwtValidator

    # -- tokens

    def token(
        self,
        object_id: str = MAPPED_OID,
        *,
        kind: str = "entra",
        roles: Sequence[str] | None = ("admin",),
        groups: Sequence[str] | None = None,
        scp: str | None = SCP,
        cloud: CloudName | None = None,
        tenant: str = TENANT,
        audience: str = AUDIENCE,
        lifetime: int = LIFETIME,
        extra: dict[str, Any] | None = None,
    ) -> str:
        now = int(self.clock.now)
        if kind == "entra":
            issuer = v2_issuer(cloud or self.cloud, tenant)
        else:
            issuer = dev_issuer(CUSTOMER).issuer
        claims: dict[str, Any] = {
            "iss": issuer,
            "aud": audience,
            "tid": tenant,
            "oid": object_id,
            "sub": f"sub-{object_id}",
            "ver": "2.0",
            "iat": now,
            "nbf": now,
            "exp": now + lifetime,
        }
        if roles is not None:
            claims["roles"] = list(roles)
        if groups is not None:
            claims["groups"] = list(groups)
        if scp is not None:
            claims["scp"] = scp
        claims.update(extra or {})
        signer = entra_signer() if kind == "entra" else dev_issuer(CUSTOMER)
        return signer.sign(claims)

    def bearer(self, object_id: str = MAPPED_OID, **kw: Any) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token(object_id, **kw)}"}

    # -- calls

    def get(self, path: str, headers: dict[str, str]) -> Any:
        return self.client.get(path, headers=headers)

    def derive(self, headers: dict[str, str]) -> ScopeDerivation:
        deriver = self.app.state.authz.scope_source
        assert isinstance(deriver, ScopeDeriver)

        async def go() -> ScopeDerivation:
            claims = await self.validator.authenticate(headers["Authorization"])
            return await deriver.derive(claims)

        return asyncio.run(go())

    # -- stores

    def register(self, *domains: str) -> None:
        admin = DomainAdmin(self.admin_config, cloud=self.cloud.value)
        for domain in domains:
            asyncio.run(
                admin.create(
                    CUSTOMER,
                    DomainDefinition.model_validate(
                        {
                            "schema_version": "1.0.0",
                            "domain_id": domain,
                            "display_name": domain.rsplit(":", 1)[-1].title(),
                            "classification": "internal",
                            "residency_region": "eastus2",
                            "status": "active",
                            "is_control_domain": False,
                        }
                    ),
                    updated_by=pid(STORED_ADMIN_OID, self.cloud),
                )
            )

    def retire(self, domain: str) -> None:
        admin = DomainAdmin(self.admin_config, cloud=self.cloud.value)
        current = asyncio.run(admin.get(CUSTOMER, domain))
        assert current is not None
        asyncio.run(
            admin.retire(
                CUSTOMER,
                domain,
                if_match=current.etag.root,
                updated_by=pid(STORED_ADMIN_OID, self.cloud),
            )
        )

    def policy_snapshot(self) -> tuple[Any, ...]:
        return (
            dict(self.repo._principals),  # pyright: ignore[reportPrivateUsage]
            dict(self.repo._heads),  # pyright: ignore[reportPrivateUsage]
        )

    def chains(self) -> list[str]:
        docs = self.audit_store._docs  # pyright: ignore[reportPrivateUsage]
        return sorted({chain for chain, _doc in docs})

    def documents(self) -> list[dict[str, Any]]:
        """Every stored audit record document, all chains (raw, as persisted)."""
        out: list[dict[str, Any]] = []
        for chain in self.chains():
            out.extend(self.audit_store.raw_documents(chain))
        return out

    def records(self) -> list[Any]:
        out: list[Any] = []
        for chain in self.chains():
            out.extend(asyncio.run(self.audit.read_range(chain, limit=500)))
        return out

    def applied(self) -> list[Any]:
        return [r for r in self.records() if r.operation == CLAIM_ROLE_APPLIED]

    def denied(self) -> list[Any]:
        return [r for r in self.records() if r.kind == "denied"]


def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in sorted(os.environ):
        if name.startswith(_PREFIXES) or name in _NAMES:
            monkeypatch.delenv(name, raising=False)


def compose_stack(
    monkeypatch: pytest.MonkeyPatch,
    *,
    mapping: str | None,
    cloud: CloudName = CloudName.COMMERCIAL,
    env: str = "local",
    audiences: Sequence[str] = (AUDIENCE,),
    seed: Callable[[InMemoryPolicyRepository], None] | None = None,
) -> Stack:
    _clean_env(monkeypatch)
    monkeypatch.setenv("NS_ENV", env)
    monkeypatch.setenv("NS_AUTH_TENANT_ID", TENANT)
    monkeypatch.setenv("NS_AUTH_AUDIENCES", ",".join(audiences))
    monkeypatch.setenv("NS_AUTH_CUSTOMER_ID", CUSTOMER)
    if mapping is not None:
        monkeypatch.setenv("NS_AUTH_ROLE_MAPPINGS", mapping)
    if env != "local":
        # A non-local deployment with the suite's test seams: the override guard is lifted for
        # this composition only, and the pseudonym key comes from settings (no local dev key).
        monkeypatch.setattr(
            "neurosphere_api.runtime.compose.refuse_overrides_outside_local", lambda *_: None
        )
        monkeypatch.setenv("NS_AUTH_PSEUDONYM_KEY", "k" * 40)
        monkeypatch.setenv(
            "NS_AUTH_PSEUDONYM_KEY_REFERENCE",
            "https://ns-test-kv.vault.azure.net/secrets/pseudonym",
        )
    clock = FakeClock()
    repo = InMemoryPolicyRepository()
    if seed is not None:
        seed(repo)
    audit_store = InMemoryAuditStore()
    audit = AuditRepository(audit_store)
    admin_config = InMemoryAdminConfigRepository(cloud=cloud.value)
    jwt_config = JwtConfig(
        env="local",
        cloud=cloud,
        tenant_id=TENANT,
        audiences=tuple(audiences),
        dev_issuer=dev_issuer(CUSTOMER).trust(),
    )
    jwks = JwksCache(
        _EntraJwks(entra_jwks_uri(cloud, TENANT)),
        clock=clock,
        ttl_seconds=3600,
        min_refresh_interval_seconds=300,
    )
    validator = JwtValidator(jwt_config, jwks, clock=clock)
    overrides = CompositionOverrides(
        authenticator=validator,
        policy_repository=repo,
        revocation_store=InMemoryRevocationStore(clock=clock),
        clock=clock,
        backends={"admin_config_repository": admin_config},
    )
    settings = Settings(env=env, cloud=cloud)  # pyright: ignore[reportArgumentType]
    app = create_app(settings)
    registry = compose_app(app, settings, overrides, builders=_builders(audit), env_probes=())
    client = TestClient(app, raise_server_exceptions=False)
    return Stack(
        app=app,
        registry=registry,
        client=client,
        clock=clock,
        cloud=cloud,
        repo=repo,
        audit_store=audit_store,
        audit=audit,
        admin_config=admin_config,
        validator=validator,
    )


def _stored(
    object_id: str,
    role: Role,
    domains: tuple[str, ...],
    *,
    cloud: CloudName = CloudName.COMMERCIAL,
) -> PrincipalPolicy:
    principal = pid(object_id, cloud)
    return PrincipalPolicy(
        id=principal_document_id(principal),
        customer_id=CUSTOMER,
        principal_id=principal,
        domain_memberships=domains,
        role_assignments=(
            PolicyRoleAssignment(
                assignment_id="ra-prp138",
                role=role,
                domain_ids=domains,
                expires_at=datetime(2030, 1, 1, tzinfo=UTC),
            ),
        ),
    )


def seed_policy(repo: InMemoryPolicyRepository) -> None:
    """A deployment admin, a finance-only domain admin and a stored viewer document for the
    principal that ALSO receives the mapped admin role (self-modification case)."""
    repo.put_head(PolicyHead(customer_id=CUSTOMER, policy_version=POLICY_VERSION))
    repo.put_principal(_stored(STORED_ADMIN_OID, Role.ADMIN, (FIN, CONTROL)))
    repo.put_principal(_stored(DOMAIN_ADMIN_OID, Role.ADMIN, (FIN,)))
    repo.put_principal(_stored(SELF_OID, Role.VIEWER, (FIN,)))


@pytest.fixture
def first_admin(monkeypatch: pytest.MonkeyPatch) -> Iterator[Stack]:
    """Mapping ``roles: admin -> admin, all, control``; EMPTY policy store and registry."""
    stack = compose_stack(monkeypatch, mapping=mapping_json(entry()))
    yield stack
    stack.client.close()


@pytest.fixture
def mapped(monkeypatch: pytest.MonkeyPatch) -> Iterator[Stack]:
    """Mapping with an app role entry and a groups entry, over a seeded policy store."""
    stack = compose_stack(monkeypatch, mapping=mapping_json(entry(), GROUP_ENTRY), seed=seed_policy)
    yield stack
    stack.client.close()


@pytest.fixture
def unmapped(monkeypatch: pytest.MonkeyPatch) -> Iterator[Stack]:
    """The default: NO mapping configured."""
    stack = compose_stack(monkeypatch, mapping=None)
    yield stack
    stack.client.close()


def _role_rows(scope: IdentityScope) -> list[dict[str, Any]]:
    return [r.model_dump(mode="json") for r in scope.to_contract().roles]


def _exp(headers: dict[str, str]) -> datetime:
    token = headers["Authorization"].split(" ", 1)[1]
    payload = jwt.decode(token, options={"verify_signature": False})
    return datetime.fromtimestamp(payload["exp"], UTC)


def _zulu(value: datetime) -> str:
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


# ============================================================================ 1. first admin


def test_first_admin_from_an_entra_app_role_on_an_empty_deployment(first_admin: Stack) -> None:
    stack = first_admin
    before = stack.policy_snapshot()
    assert before == ({}, {})  # no policy head, no principal document
    assert asyncio.run(DomainAdmin(stack.admin_config, cloud="commercial").list(CUSTOMER)) == []

    response = stack.get(STATUS, stack.bearer(roles=["admin"]))

    assert response.status_code == 200, response.text
    assert stack.policy_snapshot() == before  # nothing written to the policy store
    assert stack.denied() == []


# ============================================================================ 2. all domains


def test_all_domains_entry_tracks_the_registry_through_the_directory_cache(
    first_admin: Stack,
) -> None:
    stack = first_admin
    stack.register(FIN, OPS, HR)
    headers = stack.bearer()

    derivation = stack.derive(headers)
    rows = _role_rows(derivation.scope)
    assert len(rows) == 1
    assert rows[0]["role"] == "admin"
    assert rows[0]["domain_ids"] == sorted([CONTROL, FIN, OPS, HR])
    assert rows[0]["expires_at"] == _zulu(_exp(headers))
    assert derivation.assignment_ids == ("entra.ns-admins",)

    # A fourth domain: not yet visible inside the cache time, visible after it, no config change.
    stack.register(SALES)
    assert SALES not in _role_rows(stack.derive(headers).scope)[0]["domain_ids"]
    stack.clock.advance(31)
    assert _role_rows(stack.derive(headers).scope)[0]["domain_ids"] == sorted(
        [CONTROL, FIN, OPS, HR, SALES]
    )

    # A retired domain drops out the same way.
    stack.retire(OPS)
    stack.clock.advance(31)
    assert _role_rows(stack.derive(headers).scope)[0]["domain_ids"] == sorted(
        [CONTROL, FIN, HR, SALES]
    )
    access = stack.get(ME_ACCESS, headers).json()
    assert [r["domain_count"] for r in access["roles"]] == [4]


# ============================================================================ 3. admin routes


@pytest.mark.parametrize("route", ROUTES, ids=lambda r: r.name)
def test_mapped_admin_passes_every_deployment_scoped_route(
    first_admin: Stack, route: Route
) -> None:
    stack = first_admin
    response = stack.client.request(
        route.method, route.path, headers=stack.bearer(), json=route.body
    )
    assert response.status_code not in (401, 403), response.text
    # Past authorization: the unconfigured plane (or body validation) answers, never a derivation
    # or authz failure.
    assert response.json().get("reason") not in _AUTHZ_FAILURES, response.text
    assert stack.denied() == []
    assert len(stack.applied()) == 1  # the role came from the mapping


_AUTHZ_FAILURES: Final = frozenset(
    {
        "authz_unconfigured",
        "audit_write_failed",
        "domain_directory_unavailable",
        "role_mapping_domain_overflow",
        "policy_store_unavailable",
        "revocation_unavailable",
    }
)


# ============================================================================ 4. no mapping


def test_without_a_mapping_role_and_group_claims_change_nothing(unmapped: Stack) -> None:
    stack = unmapped
    claimed = stack.bearer(roles=["admin"], groups=[GROUP])
    plain = stack.bearer(roles=None)

    with_claims = stack.derive(claimed).scope.to_contract().model_dump(mode="json")
    without = stack.derive(plain).scope.to_contract().model_dump(mode="json")
    assert with_claims == without  # byte for byte the scope of a token without the claims
    assert with_claims["roles"] == []

    response = stack.get(STATUS, claimed)
    assert response.status_code == 403, response.text
    assert response.json()["reason"] == "permission_missing"
    assert [r.denial.reason for r in stack.denied()] == ["permission_missing"]
    assert stack.applied() == []

    access = stack.get(ME_ACCESS, claimed)
    assert access.status_code == 200, access.text
    assert access.json() == {"mapping_configured": False, "groups_overage": False, "roles": []}
    assert claim_mapping_stats(stack.app.state) is None


# ============================================================================ 5. negatives


def _assert_unmapped(stack: Stack, headers: dict[str, str]) -> None:
    response = stack.get(STATUS, headers)
    assert response.status_code == 403, response.text
    assert response.json()["reason"] == "permission_missing"
    access = stack.get(ME_ACCESS, headers)
    assert access.status_code == 200, access.text
    assert access.json()["roles"] == []
    assert access.json()["mapping_configured"] is True
    assert stack.applied() == []


def test_role_value_not_in_the_mapping(first_admin: Stack) -> None:
    _assert_unmapped(first_admin, first_admin.bearer(roles=["Admin", "admins", "reader"]))


def test_absent_roles_claim(first_admin: Stack) -> None:
    _assert_unmapped(first_admin, first_admin.bearer(roles=None))


def test_token_of_another_tenant_is_refused(first_admin: Stack) -> None:
    stack = first_admin
    response = stack.get(STATUS, stack.bearer(tenant=OTHER_TENANT))
    assert response.status_code == 401, response.text
    assert stack.applied() == []


def test_mapping_bound_to_another_tenant_grants_nothing() -> None:
    """A mapping copied from another deployment (its tenant) never maps this tenant's token.

    The composed builder refuses such a mapping at startup (see the startup tests), so the
    request-time tenant check is exercised on the deriver itself with a token of THIS tenant.
    """
    mapping = parse_claim_role_mapping(mapping_json(tenant_id=OTHER_TENANT))
    assert mapping is not None
    clock = FakeClock()
    seen: list[tuple[ClaimGrant, ...]] = []

    class Observer:
        async def on_claim_grants(
            self,
            scope: IdentityScope,
            grants: tuple[ClaimGrant, ...],
            issued_at: datetime,
            expires_at: datetime,
        ) -> None:
            seen.append(grants)

    class Directory:
        async def active_domain_ids(self, customer_id: str) -> tuple[str, ...]:
            return (FIN,)

    deriver = ScopeDeriver(
        ScopeDerivationConfig(cloud=CloudName.COMMERCIAL, tenant_id=TENANT, customer_id=CUSTOMER),
        policy_repository=InMemoryPolicyRepository(),
        pseudonymizer=PrincipalPseudonymizer(local_dev_pseudonym_key()),
        revocation_checker=NoRevocationCheck(),
        clock=clock,
        claim_mapping=mapping,
        domain_directory=Directory(),
        claim_grant_observer=Observer(),
        allow_dev_issuer=False,
    )
    derivation = asyncio.run(deriver.derive(_claims(clock, roles=("admin",))))
    assert derivation.scope.to_contract().roles == []
    assert derivation.claim_grants == ()
    assert seen == []
    # Positive control: the same deriver shape bound to THIS tenant maps the same claims.
    bound = parse_claim_role_mapping(mapping_json())
    assert bound is not None
    deriver_ok = ScopeDeriver(
        deriver.config,
        policy_repository=InMemoryPolicyRepository(),
        pseudonymizer=PrincipalPseudonymizer(local_dev_pseudonym_key()),
        revocation_checker=NoRevocationCheck(),
        clock=clock,
        claim_mapping=bound,
        domain_directory=Directory(),
        claim_grant_observer=Observer(),
        allow_dev_issuer=False,
    )
    granted = asyncio.run(deriver_ok.derive(_claims(clock, roles=("admin",))))
    assert [g.entry_id for g in granted.claim_grants] == ["ns-admins"]


def _claims(
    clock: FakeClock,
    *,
    roles: tuple[str, ...],
    cloud: CloudName = CloudName.COMMERCIAL,
    audience: str = AUDIENCE,
) -> VerifiedClaims:
    now = datetime.fromtimestamp(clock.now, UTC)
    return VerifiedClaims(
        issuer_kind="entra",
        cloud=cloud,
        issuer=v2_issuer(cloud, TENANT),
        audience=audience,
        tenant_id=TENANT,
        object_id=MAPPED_OID,
        subject=f"sub-{MAPPED_OID}",
        token_version="2.0",
        issued_at=now,
        not_before=now,
        expires_at=datetime.fromtimestamp(clock.now + LIFETIME, UTC),
        identity_type="user",
        roles=roles,
        scopes=(SCP,),
    )


def test_token_of_another_audience_is_never_mapped(monkeypatch: pytest.MonkeyPatch) -> None:
    """Both audiences are accepted by the deployment; the mapping is bound to the first one."""
    stack = compose_stack(
        monkeypatch, mapping=mapping_json(), audiences=(AUDIENCE, SECOND_AUDIENCE)
    )
    with stack.client:
        _assert_unmapped(stack, stack.bearer(audience=SECOND_AUDIENCE))
        # Positive control: the bound audience maps.
        assert stack.get(STATUS, stack.bearer(SECOND_OID)).status_code == 200
    # An audience the deployment does not accept at all is refused outright.
    with stack.client:
        refused = stack.get(STATUS, stack.bearer(audience="api://somebody-else"))
    assert refused.status_code == 401


def test_local_test_issuer_outside_local_is_never_mapped(monkeypatch: pytest.MonkeyPatch) -> None:
    stack = compose_stack(monkeypatch, mapping=mapping_json(), env="dev")
    assert stack.registry.get("authz").state == "ok"
    with stack.client:
        dev_token = stack.bearer(kind="dev")
        response = stack.get(STATUS, dev_token)
        assert response.status_code == 403, response.text
        assert response.json()["reason"] == "permission_missing"
        assert stack.applied() == []
        # Positive control: the same deployment maps an Entra token carrying the same role.
        assert stack.get(STATUS, stack.bearer(SECOND_OID)).status_code == 200


def test_local_test_issuer_in_local_is_mapped(first_admin: Stack) -> None:
    """The counterpart of the test above: ``NS_ENV=local`` accepts the local issuer."""
    assert first_admin.get(STATUS, first_admin.bearer(kind="dev")).status_code == 200


def test_app_only_token_is_never_mapped(first_admin: Stack) -> None:
    _assert_unmapped(first_admin, first_admin.bearer(scp=None, extra={"idtyp": "app"}))


def test_app_only_token_with_a_scope_is_still_never_mapped(first_admin: Stack) -> None:
    _assert_unmapped(first_admin, first_admin.bearer(extra={"idtyp": "app"}))


def test_token_without_scp_is_never_mapped(first_admin: Stack) -> None:
    _assert_unmapped(first_admin, first_admin.bearer(scp=None))


class _NoOutbound:
    """Records every attempt to open an outbound HTTP connection (none may happen)."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.calls: list[str] = []

        def sync(transport: Any, request: httpx.Request) -> Any:
            self.calls.append(str(request.url))
            raise AssertionError("outbound HTTP call")

        async def asyn(transport: Any, request: httpx.Request) -> Any:
            self.calls.append(str(request.url))
            raise AssertionError("outbound HTTP call")

        def opener(*args: Any, **kwargs: Any) -> Any:
            self.calls.append("urllib")
            raise AssertionError("outbound HTTP call")

        monkeypatch.setattr(httpx.HTTPTransport, "handle_request", sync)
        monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", asyn)
        monkeypatch.setattr(urllib.request, "urlopen", opener)


@pytest.mark.parametrize(
    "overage",
    [{"hasgroups": True}, {"_claim_names": {"groups": "src1"}}],
    ids=["hasgroups", "claim_names"],
)
def test_group_overage_applies_role_entries_only(
    mapped: Stack, monkeypatch: pytest.MonkeyPatch, overage: dict[str, Any]
) -> None:
    stack = mapped
    outbound = _NoOutbound(monkeypatch)
    headers = stack.bearer(roles=["admin"], groups=[GROUP], extra=overage)

    access = stack.get(ME_ACCESS, headers)

    assert access.status_code == 200, access.text
    body = access.json()
    assert body["groups_overage"] is True
    assert [(r["role"], r["source"], r["mapping_entry_id"]) for r in body["roles"]] == [
        ("admin", "entra_app_role", "ns-admins")
    ]
    derivation = stack.derive(headers)
    assert [g.entry_id for g in derivation.claim_grants] == ["ns-admins"]
    stats = claim_mapping_stats(stack.app.state)
    assert stats is not None
    assert stats.snapshot()["groups_overage"] >= 1
    assert outbound.calls == []


# ============================================================================ 6. groups


def test_groups_entry_applies_for_the_object_id(mapped: Stack) -> None:
    stack = mapped
    headers = stack.bearer(roles=None, groups=[GROUP.upper()])
    access = stack.get(ME_ACCESS, headers).json()
    assert [(r["role"], r["source"], r["mapping_entry_id"]) for r in access["roles"]] == [
        ("analyst", "entra_group", "finance-analysts")
    ]
    domains = stack.get(ME_DOMAINS, headers)
    assert domains.status_code == 200, domains.text
    assert [d["domain_id"] for d in domains.json()["items"]] == [FIN]
    # Another group id maps nothing.
    other = stack.bearer(SECOND_OID, roles=None, groups=[str(uuid.uuid5(uuid.NAMESPACE_URL, "x"))])
    assert stack.get(ME_ACCESS, other).json()["roles"] == []


# ============================================================================ 7. no bypass


def test_mapped_admin_holds_exactly_the_admin_permission_set(first_admin: Stack) -> None:
    stack = first_admin
    stack.register(FIN)
    scope = stack.derive(stack.bearer()).scope
    now = stack.clock.dt()
    for domain in (CONTROL, FIN):
        held = {p for p in Permission if permits(scope, p, now=now, domain_id=domain)}
        assert held == set(role_permissions(Role.ADMIN)), domain
    assert Permission.ACTION_APPROVE not in role_permissions(Role.ADMIN)
    assert Permission.AUDIT_READ not in role_permissions(Role.ADMIN)
    assert [r["role"] for r in _role_rows(scope)] == ["admin"]


def test_mapped_admin_cannot_approve_actions(first_admin: Stack) -> None:
    stack = first_admin
    stack.register(FIN)
    response = stack.client.post(
        f"/api/v1/actions/domains/{FIN}/intents/{uuid.uuid4()}/decisions",
        headers=stack.bearer(),
        json={
            "decision": "approved",
            "reason": "looks fine",
            "confirmation_hash": "sha256:" + "0" * 64,
        },
    )
    assert response.status_code == 403, response.text
    # A domain-targeted route: the admin holds the domain, not the permission on it.
    assert response.json()["reason"] == "target_out_of_scope"
    assert "action.approve" in response.json()["detail"]
    assert [r.denial.reason for r in stack.denied()] == ["target_out_of_scope"]


@pytest.mark.parametrize("path", ["/api/v1/audit/search", "/api/v1/audit/denials"])
def test_mapped_admin_cannot_read_audit(first_admin: Stack, path: str) -> None:
    stack = first_admin
    stack.register(FIN)
    response = stack.get(path, stack.bearer())
    assert response.status_code == 403, response.text
    assert "audit.read" in response.json()["detail"]


def test_mapped_admin_cannot_change_its_own_policy_document(mapped: Stack) -> None:
    stack = mapped
    stack.register(FIN)  # the mapped admin manages finance, where its stored document lives
    me = pid(SELF_OID)
    headers = stack.bearer(SELF_OID)
    detail = stack.get(f"{PRINCIPALS}/{me}", headers)
    assert detail.status_code == 200, detail.text  # reading your own access is not a change
    before = stack.policy_snapshot()
    expires = _zulu(stack.clock.dt(3600))
    response = stack.client.put(
        f"{PRINCIPALS}/{me}/role-assignments/ra-new",
        headers={**headers, "If-Match": detail.headers["ETag"]},
        json={
            "schema_version": "1.0.0",
            "op": "assign",
            "principal_id": me,
            "assignment_id": "ra-new",
            "role": "security_auditor",
            "domain_ids": [FIN],
            "expires_at": expires,
            "reason": "access_request",
        },
    )
    assert response.status_code == 403, response.text
    assert response.json()["reason"] == "self_modification_forbidden"
    assert stack.policy_snapshot() == before


# ============================================================================ 8. clouds


def test_commercial_mapping_never_maps_a_government_token(first_admin: Stack) -> None:
    stack = first_admin
    response = stack.get(STATUS, stack.bearer(cloud=CloudName.GOVERNMENT))
    assert response.status_code == 401, response.text
    assert stack.applied() == []


def test_government_mapping_never_maps_a_commercial_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stack = compose_stack(monkeypatch, mapping=mapping_json(), cloud=CloudName.GOVERNMENT)
    assert stack.registry.get("authz").state == "ok"
    with stack.client:
        refused = stack.get(STATUS, stack.bearer(cloud=CloudName.COMMERCIAL))
        assert refused.status_code == 401, refused.text
        assert stack.applied() == []
        # Positive control: the Government token maps, on the Government control domain only.
        headers = stack.bearer(SECOND_OID, cloud=CloudName.GOVERNMENT)
        assert stack.get(STATUS, headers).status_code == 200
        rows = _role_rows(stack.derive(headers).scope)
        assert [r["domain_ids"] for r in rows] == [[GOV_CONTROL]]


def test_deriver_refuses_claims_of_the_other_cloud_before_mapping() -> None:
    """Even a validated claim set of the other cloud never reaches the mapping."""
    mapping = parse_claim_role_mapping(mapping_json())
    assert mapping is not None
    clock = FakeClock()
    seen: list[str] = []

    class Observer:
        async def on_claim_grants(
            self,
            scope: IdentityScope,
            grants: tuple[ClaimGrant, ...],
            issued_at: datetime,
            expires_at: datetime,
        ) -> None:
            seen.append("called")

    class Directory:
        async def active_domain_ids(self, customer_id: str) -> tuple[str, ...]:
            seen.append("directory")
            return ()

    for deployment, token in (
        (CloudName.COMMERCIAL, CloudName.GOVERNMENT),
        (CloudName.GOVERNMENT, CloudName.COMMERCIAL),
    ):
        deriver = ScopeDeriver(
            ScopeDerivationConfig(cloud=deployment, tenant_id=TENANT, customer_id=CUSTOMER),
            policy_repository=InMemoryPolicyRepository(),
            pseudonymizer=PrincipalPseudonymizer(local_dev_pseudonym_key()),
            revocation_checker=NoRevocationCheck(),
            clock=clock,
            claim_mapping=mapping,
            domain_directory=Directory(),
            claim_grant_observer=Observer(),
        )
        with pytest.raises(UnauthorizedError) as caught:
            asyncio.run(deriver.derive(_claims(clock, roles=("admin",), cloud=token)))
        assert caught.value.reason == "cloud"
    assert seen == []


# ============================================================================ 9. time, revocation


def test_mapped_assignment_expires_at_the_token_expiry(first_admin: Stack) -> None:
    stack = first_admin
    headers = stack.bearer(lifetime=600)
    exp = _exp(headers)
    rows = _role_rows(stack.derive(headers).scope)
    assert [r["expires_at"] for r in rows] == [_zulu(exp)]
    access = stack.get(ME_ACCESS, headers).json()
    assert [r["expires_at"] for r in access["roles"]] == [_zulu(exp)]
    assert stack.get(STATUS, headers).status_code == 200
    stack.clock.advance(601)  # past exp (and the validator's leeway)
    assert stack.get(STATUS, headers).status_code == 401


def test_new_token_without_the_role_maps_nothing(first_admin: Stack) -> None:
    stack = first_admin
    assert stack.get(STATUS, stack.bearer()).status_code == 200
    stack.clock.advance(5)  # the app role was removed in Entra; the next token lacks it
    after = stack.bearer(roles=["reader"])
    response = stack.get(STATUS, after)
    assert response.status_code == 403, response.text
    assert stack.get(ME_ACCESS, after).json()["roles"] == []


def test_revoked_mapped_principal_is_refused_before_mapping(mapped: Stack) -> None:
    stack = mapped
    mapped_headers = stack.bearer()
    assert stack.get(STATUS, mapped_headers).status_code == 200
    applied_before = len(stack.applied())

    stack.clock.advance(1)
    revoke = stack.client.post(
        f"{PRINCIPALS}/{pid(MAPPED_OID)}/revocation",
        headers=stack.bearer(STORED_ADMIN_OID, roles=None),
        json={"schema_version": "1.0.0", "reason": "compromised", "mode": "until_lifted"},
    )
    assert revoke.status_code in (200, 201), revoke.text

    old = stack.get(STATUS, mapped_headers)
    assert old.status_code == 403, old.text
    assert old.json()["reason"] == "principal_revoked"
    stack.clock.advance(5)
    fresh = stack.get(STATUS, stack.bearer())  # a new token still carrying the app role
    assert fresh.status_code == 403, fresh.text
    assert fresh.json()["reason"] == "principal_revoked"
    assert len(stack.applied()) == applied_before  # the mapping never ran for either token


# ============================================================================ 10. audit


def test_one_audit_record_per_token(first_admin: Stack) -> None:
    stack = first_admin
    first = stack.bearer()
    for _ in range(3):
        assert stack.get(STATUS, first).status_code == 200
    records = stack.applied()
    assert len(records) == 1
    assert records[0].actor.principal_pseudonym == pid(MAPPED_OID).rsplit(":", 1)[-1]

    stack.clock.advance(2)
    second = stack.bearer()
    assert second != first
    assert stack.get(STATUS, second).status_code == 200
    assert stack.get(STATUS, second).status_code == 200
    assert len(stack.applied()) == 2


def test_audit_record_carries_metadata_only(monkeypatch: pytest.MonkeyPatch) -> None:
    group_admin = entry(id="ns-group-admins", claim="groups", value=GROUP)
    stack = compose_stack(monkeypatch, mapping=mapping_json(entry(value=ROLE_VALUE), group_admin))
    with stack.client:
        token = stack.token(
            roles=[ROLE_VALUE, "reader"],
            groups=[GROUP],
            extra={"name": "Alice Example", "preferred_username": "alice@contoso.example"},
        )
        response = stack.get(STATUS, {"Authorization": f"Bearer {token}"})
    assert response.status_code == 200, response.text
    records = stack.applied()
    assert len(records) == 1
    record = records[0]
    assert record.operation == CLAIM_ROLE_APPLIED
    detail = record.outcome.detail
    assert "entries=ns-admins.ns-group-admins" in detail
    assert "roles=admin" in detail
    stored = [d for d in stack.documents() if d.get("operation") == CLAIM_ROLE_APPLIED]
    assert len(stored) == 1
    # ``audit_id`` is the record's own random id, generated by the audit store layer; every
    # other field is checked for GUID-shaped values (object ids, group ids, tenant ids).
    document = {k: v for k, v in stored[0].items() if k != "audit_id"}
    uuid.UUID(stored[0]["audit_id"])
    assert stored[0]["audit_id"] not in (GROUP, MAPPED_OID, TENANT)
    text = json.dumps(document)
    for forbidden in (
        token,
        *token.split("."),
        ROLE_VALUE,
        "reader",
        GROUP,
        GROUP.upper(),
        MAPPED_OID,
        TENANT,
        "Alice",
        "alice@",
        AUDIENCE,
    ):
        assert forbidden not in text, forbidden
    assert GUID.search(text) is None, GUID.search(text)


def test_audit_write_failure_refuses_the_request(first_admin: Stack) -> None:
    stack = first_admin
    stack.audit_store.fail_with = RuntimeError("audit store down")
    headers = stack.bearer()
    response = stack.get(STATUS, headers)
    assert response.status_code == 503, response.text
    assert response.json()["reason"] == "audit_write_failed"
    stack.audit_store.fail_with = None
    # Not remembered after a failed write: the next request writes the record and passes.
    assert stack.get(STATUS, headers).status_code == 200
    assert len(stack.applied()) == 1


# ============================================================================ 11. read views


def test_role_mapping_view_through_the_composed_app(mapped: Stack) -> None:
    stack = mapped
    response = stack.get(ROLE_MAPPING, stack.bearer())
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["active"] is True
    assert (body["tenant_id"], body["audience"], body["cloud"]) == (TENANT, AUDIENCE, "commercial")
    assert {
        "id": "ns-admins",
        "claim": "roles",
        "value": "admin",
        "role": "admin",
        "domain_mode": "all",
        "domain_ids": [],
        "customer_control": True,
    } in body["entries"]
    assert [e["id"] for e in body["entries"]] == ["ns-admins", "finance-analysts"]


def test_role_mapping_view_needs_the_control_domain(mapped: Stack) -> None:
    stack = mapped
    response = stack.get(ROLE_MAPPING, stack.bearer(DOMAIN_ADMIN_OID, roles=None))
    assert response.status_code == 403, response.text
    assert response.json()["reason"] == "customer_scope_required"
    assert "policy.manage" in response.json()["detail"]


def test_role_mapping_view_is_open_to_a_stored_deployment_admin(mapped: Stack) -> None:
    response = mapped.get(ROLE_MAPPING, mapped.bearer(STORED_ADMIN_OID, roles=None))
    assert response.status_code == 200, response.text
    assert response.json()["active"] is True


def test_me_access_names_the_entra_source(mapped: Stack) -> None:
    stack = mapped
    headers = stack.bearer(SELF_OID)
    response = stack.get(ME_ACCESS, headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["mapping_configured"] is True
    assert body["groups_overage"] is False
    rows = sorted((r["role"], r["source"], r["mapping_entry_id"], r["customer_control"])
                  for r in body["roles"])  # fmt: skip
    assert rows == [
        ("admin", "entra_app_role", "ns-admins", True),
        ("viewer", "policy_store", None, False),
    ]
    admin_row = next(r for r in body["roles"] if r["source"] == "entra_app_role")
    assert admin_row["expires_at"] == _zulu(_exp(headers))
    for leaked in (GROUP, TENANT, AUDIENCE, CONTROL, FIN):
        assert leaked not in response.text, leaked


# ============================================================================ 12. startup


@pytest.mark.parametrize(
    ("raw", "reason"),
    [
        (mapping_json(tenant_id=OTHER_TENANT), "role_mapping_binding_mismatch"),
        (mapping_json(audience="api://another-api"), "role_mapping_binding_mismatch"),
        ("{not json", "role_mapping_invalid"),
        (mapping_json(entry(role="superuser")), "role_mapping_invalid"),
        (mapping_json(entry(), entry(value="other")), "role_mapping_invalid"),
        (mapping_json(entry(), entry(id="ns-viewers", role="viewer")), "role_mapping_invalid"),
        (mapping_json(entry(claim="groups", value="NeuroSphere Admins")), "role_mapping_invalid"),
        (mapping_json(entry(domains=[GOV_FIN])), "role_mapping_invalid"),
        (
            mapping_json(entry(domains=["commercial:fabrikam:catalog:domain:finance"])),
            "role_mapping_invalid",
        ),
    ],
    ids=[
        "tenant_mismatch",
        "audience_mismatch",
        "malformed_json",
        "unknown_role",
        "duplicate_entry_id",
        "value_to_two_roles",
        "non_guid_group",
        "other_cloud_domain",
        "other_customer_domain",
    ],
)
def test_defective_mapping_fails_closed_at_startup(
    monkeypatch: pytest.MonkeyPatch, raw: str, reason: str
) -> None:
    stack = compose_stack(monkeypatch, mapping=raw)
    status = stack.registry.get("authz")
    assert (status.state, status.reason) == ("failed", reason)
    with stack.client:
        for path in (STATUS, ME_ACCESS, ME_DOMAINS, ROLE_MAPPING):
            response = stack.get(path, stack.bearer())
            assert response.status_code == 503, (path, response.text)
            assert response.json()["reason"] == "authz_unconfigured"
            assert raw not in response.text
        ready = stack.client.get("/readyz")
    assert ready.status_code == 503
    assert reason in ready.text
