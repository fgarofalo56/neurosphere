"""PRP-138 item 3: scope derivation applies the Entra claim role mapping, and only it.

Helpers are local on purpose: test packages with the same name in one pytest session shadow each
other, so this directory does not import ``tests/auth/scope/scope_helpers.py``. It uses the same
in-memory policy repository, fake clock and claim shapes.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from neurosphere_contracts.scope.v1.identity_scope import IdentityScope as ContractIdentityScope
from neurosphere_core.auth.jwt import VerifiedClaims
from neurosphere_core.auth.scope import (
    MAPPED_ASSIGNMENT_PREFIX,
    ClaimGrant,
    ClaimRoleMapping,
    DomainDirectory,
    InMemoryPolicyRepository,
    NoRevocationCheck,
    Permission,
    PolicyHead,
    PolicyRoleAssignment,
    PrincipalPolicy,
    PrincipalPseudonymizer,
    PseudonymKey,
    RevocationChecker,
    Role,
    ScopeDerivation,
    ScopeDerivationConfig,
    ScopeDeriver,
    customer_control_domain_id,
    domains_with_permission,
    parse_claim_role_mapping,
    permits_customer_wide,
    principal_document_id,
    role_permissions,
)
from neurosphere_core.cloud import CloudName
from neurosphere_core.errors import DependencyTransientError, ForbiddenError
from neurosphere_core.scope import IdentityScope

TENANT = "0f1e2d3c-4b5a-4968-8776-a5b4c3d2e1f0"
OTHER_TENANT = "9a8b7c6d-5e4f-4a3b-8c2d-1e0f9a8b7c6d"
AUDIENCE = "api://neurosphere-test-api"
OBJECT_ID = "6c1d2e3f-4a5b-4c6d-8e7f-90a1b2c3d4e5"
GROUP = "1a2b3c4d-5e6f-4a7b-8c9d-0e1f2a3b4c5d"
CUSTOMER = "contoso"
T0 = 1_800_000_000.0
TOKEN_LIFETIME = 3600.0
TTL = 30.0

FINANCE = "commercial:contoso:catalog:domain:finance"
OPERATIONS = "commercial:contoso:catalog:domain:operations"
HR = "commercial:contoso:catalog:domain:hr"
SALES = "commercial:contoso:catalog:domain:sales"
OTHER_CUSTOMER_FINANCE = "commercial:fabrikam:catalog:domain:finance"
GOV_FINANCE = "government:contoso:catalog:domain:finance"
CONTROL = customer_control_domain_id("commercial", CUSTOMER)


# --------------------------------------------------------------------------- helpers


class FakeClock:
    def __init__(self, now: float = T0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def at(offset_seconds: float) -> datetime:
    return datetime.fromtimestamp(T0, UTC) + timedelta(seconds=offset_seconds)


TOKEN_EXPIRY = at(TOKEN_LIFETIME)


def make_claims(**extra: Any) -> VerifiedClaims:
    fields: dict[str, Any] = {
        "issuer_kind": "entra",
        "cloud": CloudName.COMMERCIAL,
        "issuer": f"https://login.microsoftonline.com/{TENANT}/v2.0",
        "audience": AUDIENCE,
        "tenant_id": TENANT,
        "object_id": OBJECT_ID,
        "subject": "subject-" + OBJECT_ID[:8],
        "token_version": "2.0",
        "issued_at": at(-60),
        "not_before": at(-60),
        "expires_at": TOKEN_EXPIRY,
        "identity_type": "user",
        "scopes": ("access_as_user",),
    }
    fields.update(extra)
    return VerifiedClaims(**fields)


def admin_claims(**extra: Any) -> VerifiedClaims:
    return make_claims(roles=("admin",), **extra)


def _pseudonymizer() -> PrincipalPseudonymizer:
    return PrincipalPseudonymizer(
        PseudonymKey(
            bytes(range(32)),
            reference="https://ns-test-kv.vault.azure.net/secrets/principal-pseudonym-key",
        )
    )


def principal_id() -> str:
    return f"commercial:{CUSTOMER}:entra:person:{_pseudonymizer().pseudonym(TENANT, OBJECT_ID)}"


def make_repo(
    *, version: str | None = None, policy: PrincipalPolicy | None = None
) -> InMemoryPolicyRepository:
    repo = InMemoryPolicyRepository()
    if version is not None:
        repo.put_head(PolicyHead(customer_id=CUSTOMER, policy_version=version))
    if policy is not None:
        repo.put_principal(policy)
    return repo


def stored_policy(*roles: PolicyRoleAssignment, memberships: tuple[str, ...]) -> PrincipalPolicy:
    pid = principal_id()
    return PrincipalPolicy(
        id=principal_document_id(pid),
        customer_id=CUSTOMER,
        principal_id=pid,
        domain_memberships=memberships,
        role_assignments=roles,
        grants=(),
    )


def entry(
    entry_id: str = "ns-admins",
    *,
    claim: str = "roles",
    value: str = "admin",
    role: str = "admin",
    domains: str | list[str] = "all",
    customer_control: bool = True,
) -> dict[str, Any]:
    return {
        "id": entry_id,
        "claim": claim,
        "value": value,
        "role": role,
        "domains": domains,
        "customer_control": customer_control,
    }


def mapping(*entries: dict[str, Any], tenant_id: str = TENANT) -> ClaimRoleMapping:
    raw = {"tenant_id": tenant_id, "audience": AUDIENCE, "entries": list(entries) or [entry()]}
    parsed = parse_claim_role_mapping(json.dumps(raw))
    assert parsed is not None
    return parsed


class FakeDirectory:
    def __init__(self, *domains: str, error: BaseException | None = None) -> None:
        self.domains: list[str] = list(domains)
        self.error = error
        self.calls = 0
        self.result: object = None

    async def active_domain_ids(self, customer_id: str) -> tuple[str, ...]:
        self.calls += 1
        assert customer_id == CUSTOMER
        if self.error is not None:
            raise self.error
        if self.result is not None:
            return self.result  # type: ignore[return-value]  # malformed answer on purpose
        return tuple(self.domains)


class RecordingObserver:
    def __init__(self, *, fail_times: int = 0) -> None:
        self.calls: list[tuple[IdentityScope, tuple[ClaimGrant, ...], datetime, datetime]] = []
        self.fail_times = fail_times

    async def on_claim_grants(
        self,
        scope: IdentityScope,
        grants: tuple[ClaimGrant, ...],
        issued_at: datetime,
        expires_at: datetime,
    ) -> None:
        self.calls.append((scope, grants, issued_at, expires_at))
        if self.fail_times > 0:
            self.fail_times -= 1
            raise RuntimeError("audit store down")


class AlwaysRevoked:
    def __init__(self) -> None:
        self.calls = 0

    async def is_revoked(self, principal_id: str, issued_at: datetime) -> bool:
        self.calls += 1
        return True


def make_deriver(
    repo: InMemoryPolicyRepository,
    *,
    clock: FakeClock | None = None,
    revocation_checker: RevocationChecker | None = None,
    **extra: Any,
) -> ScopeDeriver:
    cfg = ScopeDerivationConfig(
        cloud=CloudName.COMMERCIAL,
        tenant_id=TENANT,
        customer_id=CUSTOMER,
        policy_cache_ttl_seconds=TTL,
    )
    return ScopeDeriver(
        cfg,
        policy_repository=repo,
        pseudonymizer=_pseudonymizer(),
        revocation_checker=revocation_checker or NoRevocationCheck(),
        clock=clock or FakeClock(),
        **extra,
    )


def mapped_deriver(
    repo: InMemoryPolicyRepository | None = None,
    *,
    claim_mapping: ClaimRoleMapping | None = None,
    directory: DomainDirectory | None = None,
    observer: RecordingObserver | None = None,
    clock: FakeClock | None = None,
    revocation_checker: RevocationChecker | None = None,
) -> ScopeDeriver:
    return make_deriver(
        repo if repo is not None else make_repo(),
        clock=clock,
        revocation_checker=revocation_checker,
        claim_mapping=claim_mapping if claim_mapping is not None else mapping(),
        domain_directory=directory,
        claim_grant_observer=observer,
    )


def contract(scope: IdentityScope) -> ContractIdentityScope:
    dumped = scope.to_contract().model_dump(mode="json", exclude_none=True)
    return ContractIdentityScope.model_validate(dumped)


def roles_of(derivation: ScopeDerivation) -> list[tuple[str, tuple[str, ...], str | None]]:
    return [
        (r.role, tuple(d.root for d in r.domain_ids), r.expires_at.root if r.expires_at else None)
        for r in contract(derivation.scope).roles
    ]


def snapshot(derivation: ScopeDerivation) -> tuple[object, ...]:
    """Everything a derivation carries, by value (``IdentityScope`` compares by identity)."""
    return (
        derivation.scope.to_contract().model_dump(mode="json"),
        derivation.assignment_ids,
        derivation.grant_ids,
        derivation.claim_grants,
    )


def allowed(derivation: ScopeDerivation) -> set[str]:
    return {d.root for d in contract(derivation.scope).allowed_domains}


EXP_TS = "2027-01-15T09:00:00Z"


# --------------------------------------------------------------------------- mapping off


def test_token_expiry_text_matches_fixture() -> None:
    assert TOKEN_EXPIRY.strftime("%Y-%m-%dT%H:%M:%SZ") == EXP_TS


async def test_mapping_off_is_byte_for_byte_today() -> None:
    policy = stored_policy(
        PolicyRoleAssignment(
            assignment_id="ra-analyst", role=Role.ANALYST, domain_ids=(FINANCE, OPERATIONS)
        ),
        memberships=(FINANCE, OPERATIONS),
    )
    plain = make_deriver(make_repo(version="2026.10.01-1", policy=policy))
    explicit = make_deriver(
        make_repo(version="2026.10.01-1", policy=policy),
        claim_mapping=None,
        domain_directory=None,
        claim_grant_observer=None,
        allow_dev_issuer=False,
    )
    baseline = await plain.derive(make_claims())
    with_defaults = await explicit.derive(make_claims())
    injected = await explicit.derive(make_claims(roles=("admin",), groups=(GROUP,)))
    # Pinned golden hash for this fixed input: a change to the mapping-off path breaks it.
    assert baseline.scope.to_contract().scope_hash == (
        "sha256:997e2f8955b8a3e88f053c3283702adcccd0b846582cfa91b759cd5fa2a94233"
    )
    golden = snapshot(baseline)
    assert snapshot(with_defaults) == golden
    assert snapshot(injected) == golden
    assert baseline.claim_grants == ()
    assert baseline.assignment_ids == ("ra-analyst",)


async def test_mapping_off_with_no_policy_head_grants_nothing_for_admin_role_claim() -> None:
    directory = FakeDirectory(FINANCE)
    observer = RecordingObserver()
    deriver = make_deriver(make_repo(), domain_directory=directory, claim_grant_observer=observer)
    derivation = await deriver.derive(admin_claims())
    scope = contract(derivation.scope)
    assert scope.roles == []
    assert scope.allowed_domains == []
    assert scope.policy_version == "none"
    assert derivation.claim_grants == ()
    assert directory.calls == 0
    assert observer.calls == []


# --------------------------------------------------------------------------- first admin


async def test_empty_store_and_registry_gives_admin_on_control_domain_only() -> None:
    repo = make_repo()
    directory = FakeDirectory()
    derivation = await mapped_deriver(repo, directory=directory).derive(admin_claims())

    assert roles_of(derivation) == [("admin", (CONTROL,), EXP_TS)]
    assert contract(derivation.scope).policy_version == "none"
    assert derivation.assignment_ids == (f"{MAPPED_ASSIGNMENT_PREFIX}ns-admins",)
    assert [g.entry_id for g in derivation.claim_grants] == ["ns-admins"]
    assert permits_customer_wide(derivation.scope, Permission.POLICY_MANAGE, now=at(0))
    # Nothing was written to the policy store.
    assert await repo.get_policy_head(CUSTOMER) is None
    assert await repo.get_principal_policy(CUSTOMER, principal_id()) is None


async def test_all_entry_without_control_and_empty_registry_grants_nothing() -> None:
    claim_mapping = mapping(entry(customer_control=False))
    observer = RecordingObserver()
    derivation = await mapped_deriver(
        claim_mapping=claim_mapping, directory=FakeDirectory(), observer=observer
    ).derive(admin_claims())
    assert roles_of(derivation) == []
    assert derivation.claim_grants == ()
    assert derivation.assignment_ids == ()
    assert observer.calls == []


async def test_registry_domains_follow_the_directory_cache() -> None:
    clock = FakeClock()
    directory = FakeDirectory(FINANCE, OPERATIONS, HR)
    deriver = mapped_deriver(directory=directory, clock=clock)

    first = await deriver.derive(admin_claims())
    assert roles_of(first) == [("admin", tuple(sorted((CONTROL, FINANCE, OPERATIONS, HR))), EXP_TS)]
    assert first.claim_grants[0].expires_at == TOKEN_EXPIRY
    assert allowed(first) == {CONTROL, FINANCE, OPERATIONS, HR}

    directory.domains = [FINANCE, OPERATIONS, SALES]  # HR retired, SALES registered
    clock.advance(TTL / 2)
    cached = await deriver.derive(admin_claims())
    assert roles_of(cached)[0][1] == tuple(sorted((CONTROL, FINANCE, OPERATIONS, HR)))
    assert directory.calls == 1

    clock.advance(TTL)
    later = await deriver.derive(admin_claims())
    assert roles_of(later) == [
        ("admin", tuple(sorted((CONTROL, FINANCE, OPERATIONS, SALES))), EXP_TS)
    ]
    assert directory.calls == 2


async def test_explicit_list_drops_foreign_cloud_and_customer_domains() -> None:
    claim_mapping = mapping(
        entry(
            "ns-analysts",
            value="Analyst.Read",
            role="analyst",
            domains=[FINANCE, OTHER_CUSTOMER_FINANCE, GOV_FINANCE],
            customer_control=False,
        )
    )
    directory = FakeDirectory(HR)
    derivation = await mapped_deriver(claim_mapping=claim_mapping, directory=directory).derive(
        make_claims(roles=("Analyst.Read",))
    )
    assert roles_of(derivation) == [("analyst", (FINANCE,), EXP_TS)]
    assert allowed(derivation) == {FINANCE}
    assert directory.calls == 0  # an explicit list never reads the registry


async def test_explicit_list_of_only_foreign_domains_grants_nothing() -> None:
    claim_mapping = mapping(
        entry(domains=[OTHER_CUSTOMER_FINANCE, GOV_FINANCE], customer_control=False)
    )
    derivation = await mapped_deriver(claim_mapping=claim_mapping).derive(admin_claims())
    assert roles_of(derivation) == []
    assert derivation.claim_grants == ()


async def test_stored_and_mapped_assignment_of_same_role_both_appear() -> None:
    stored_expiry = at(1800)
    policy = stored_policy(
        PolicyRoleAssignment(
            assignment_id="ra-admin",
            role=Role.ADMIN,
            domain_ids=(FINANCE,),
            expires_at=stored_expiry,
        ),
        memberships=(FINANCE,),
    )
    repo = make_repo(version="2026.11.18-1", policy=policy)
    derivation = await mapped_deriver(repo, directory=FakeDirectory(FINANCE, HR)).derive(
        admin_claims()
    )
    scope = contract(derivation.scope)
    assert sorted(roles_of(derivation)) == sorted(
        [
            ("admin", (FINANCE,), "2027-01-15T08:30:00Z"),
            ("admin", tuple(sorted((CONTROL, FINANCE, HR))), EXP_TS),
        ]
    )
    assert derivation.assignment_ids == ("entra.ns-admins", "ra-admin")
    assert scope.policy_version == "2026.11.18-1"
    assert scope.scope_hash.startswith("sha256:")


async def test_mapped_domains_skip_the_membership_clip() -> None:
    policy = stored_policy(
        PolicyRoleAssignment(assignment_id="ra-viewer", role=Role.VIEWER, domain_ids=(FINANCE,)),
        memberships=(FINANCE,),
    )
    repo = make_repo(version="v1", policy=policy)
    derivation = await mapped_deriver(repo, directory=FakeDirectory(HR)).derive(admin_claims())
    assert ("admin", tuple(sorted((CONTROL, HR))), EXP_TS) in roles_of(derivation)


# --------------------------------------------------------------------------- denials


async def test_revoked_principal_refused_before_mapping() -> None:
    directory = FakeDirectory(FINANCE)
    observer = RecordingObserver()
    revoked = AlwaysRevoked()
    deriver = mapped_deriver(directory=directory, observer=observer, revocation_checker=revoked)
    with pytest.raises(ForbiddenError) as caught:
        await deriver.derive(admin_claims())
    assert caught.value.reason == "principal_revoked"
    assert revoked.calls == 1
    assert directory.calls == 0
    assert observer.calls == []


async def test_missing_directory_denies() -> None:
    with pytest.raises(DependencyTransientError) as caught:
        await mapped_deriver(directory=None).derive(admin_claims())
    assert caught.value.reason == "domain_directory_unavailable"


@pytest.mark.parametrize(
    "error",
    [RuntimeError("registry down"), DependencyTransientError("x", reason="other_reason")],
)
async def test_raising_directory_denies(error: BaseException) -> None:
    observer = RecordingObserver()
    directory = FakeDirectory(error=error)
    deriver = mapped_deriver(directory=directory, observer=observer)
    with pytest.raises(DependencyTransientError) as caught:
        await deriver.derive(admin_claims())
    assert caught.value.reason == "domain_directory_unavailable"
    assert observer.calls == []
    # The failure is not cached: a recovered directory is asked again.
    directory.error = None
    derivation = await deriver.derive(admin_claims())
    assert roles_of(derivation) == [("admin", (CONTROL,), EXP_TS)]
    assert directory.calls == 2


@pytest.mark.parametrize(
    "answer", [["not-a-canonical-id"], [CONTROL.replace(":domain:", ":agent:")], "x", [1]]
)
async def test_malformed_directory_answer_denies(answer: object) -> None:
    directory = FakeDirectory()
    directory.result = answer
    with pytest.raises(DependencyTransientError) as caught:
        await mapped_deriver(directory=directory).derive(admin_claims())
    assert caught.value.reason == "domain_directory_unavailable"


async def test_overflow_at_one_thousand_denies_and_never_truncates() -> None:
    many = [f"commercial:contoso:catalog:domain:d{i:04d}" for i in range(1000)]
    with pytest.raises(DependencyTransientError) as caught:
        await mapped_deriver(directory=FakeDirectory(*many)).derive(admin_claims())
    assert caught.value.reason == "role_mapping_domain_overflow"

    derivation = await mapped_deriver(directory=FakeDirectory(*many[:999])).derive(admin_claims())
    assert len(roles_of(derivation)[0][1]) == 1000  # 999 registry domains + control


# --------------------------------------------------------------------------- no match


@pytest.mark.parametrize(
    ("claim_mapping", "claims"),
    [
        pytest.param(mapping(), make_claims(roles=("viewer",)), id="unmapped-value"),
        pytest.param(mapping(), make_claims(), id="absent-roles"),
        pytest.param(mapping(tenant_id=OTHER_TENANT), admin_claims(), id="other-tenant"),
        pytest.param(mapping(), admin_claims(audience="api://another-api"), id="other-audience"),
        pytest.param(mapping(), admin_claims(identity_type="app"), id="app-only-idtyp"),
        pytest.param(mapping(), admin_claims(scopes=()), id="app-only-no-scp"),
        pytest.param(mapping(), admin_claims(issuer_kind="dev"), id="dev-issuer-not-allowed"),
    ],
)
async def test_no_match_keeps_todays_scope(
    claim_mapping: ClaimRoleMapping, claims: VerifiedClaims
) -> None:
    directory = FakeDirectory(FINANCE)
    observer = RecordingObserver()
    mapped = await mapped_deriver(
        claim_mapping=claim_mapping, directory=directory, observer=observer
    ).derive(claims)
    today = await make_deriver(make_repo()).derive(claims)
    assert snapshot(mapped) == snapshot(today)
    assert directory.calls == 0
    assert observer.calls == []


async def test_dev_issuer_maps_only_when_allowed() -> None:
    deriver = make_deriver(
        make_repo(),
        claim_mapping=mapping(),
        domain_directory=FakeDirectory(),
        allow_dev_issuer=True,
    )
    derivation = await deriver.derive(admin_claims(issuer_kind="dev"))
    assert roles_of(derivation) == [("admin", (CONTROL,), EXP_TS)]


async def test_overage_skips_group_entry_while_role_entry_applies() -> None:
    claim_mapping = mapping(
        entry(),
        entry(
            "finance-readers",
            claim="groups",
            value=GROUP,
            role="viewer",
            domains=[FINANCE],
            customer_control=False,
        ),
    )
    directory = FakeDirectory(HR)
    deriver = mapped_deriver(claim_mapping=claim_mapping, directory=directory)

    with_groups = await deriver.derive(admin_claims(groups=(GROUP,)))
    assert sorted(g.entry_id for g in with_groups.claim_grants) == ["finance-readers", "ns-admins"]

    overage = await deriver.derive(admin_claims(groups_overage=True))
    assert [g.entry_id for g in overage.claim_grants] == ["ns-admins"]
    assert [g.claim for g in overage.claim_grants] == ["roles"]


# --------------------------------------------------------------------------- observer


async def test_observer_receives_the_applied_grants() -> None:
    observer = RecordingObserver()
    claims = admin_claims()
    derivation = await mapped_deriver(directory=FakeDirectory(FINANCE), observer=observer).derive(
        claims
    )
    assert len(observer.calls) == 1
    scope, grants, issued_at, expires_at = observer.calls[0]
    assert scope == derivation.scope
    assert grants == derivation.claim_grants
    assert grants[0].role is Role.ADMIN
    assert grants[0].domain_ids == tuple(sorted((CONTROL, FINANCE)))
    assert grants[0].customer_control is True
    assert issued_at == claims.issued_at
    assert expires_at == claims.expires_at


async def test_observer_failure_denies_and_is_not_cached() -> None:
    observer = RecordingObserver(fail_times=1)
    deriver = mapped_deriver(directory=FakeDirectory(FINANCE), observer=observer)
    with pytest.raises(DependencyTransientError) as caught:
        await deriver.derive(admin_claims())
    assert caught.value.reason == "audit_write_failed"

    derivation = await deriver.derive(admin_claims())
    assert len(observer.calls) == 2  # the second success is observed again, never served cached
    assert derivation.claim_grants


# --------------------------------------------------------------------------- no bypass


async def test_mapped_admin_holds_exactly_the_admin_permission_set() -> None:
    derivation = await mapped_deriver(directory=FakeDirectory(FINANCE)).derive(admin_claims())
    now = at(0)
    held = {
        permission
        for permission in Permission
        if domains_with_permission(derivation.scope, permission, now=now)
    }
    assert held == set(role_permissions(Role.ADMIN))
    assert not permits_customer_wide(derivation.scope, Permission.ACTION_APPROVE, now=now)
    assert not permits_customer_wide(derivation.scope, Permission.AUDIT_READ, now=now)
    assert permits_customer_wide(derivation.scope, Permission.POLICY_MANAGE, now=now)
    # Time-bound: nothing is held once the token has expired.
    assert not domains_with_permission(derivation.scope, Permission.POLICY_MANAGE, now=TOKEN_EXPIRY)


async def test_mapped_viewer_is_time_bound_and_readable() -> None:
    claim_mapping = mapping(
        entry(
            "ns-viewers",
            value="viewer",
            role="viewer",
            domains=[FINANCE, OPERATIONS],
            customer_control=False,
        )
    )
    derivation = await mapped_deriver(claim_mapping=claim_mapping).derive(
        make_claims(roles=("viewer",))
    )
    assert roles_of(derivation) == [("viewer", tuple(sorted((FINANCE, OPERATIONS))), EXP_TS)]
    assert allowed(derivation) == {FINANCE, OPERATIONS}
    assert derivation.claim_grants[0].expires_at == TOKEN_EXPIRY
    assert not permits_customer_wide(derivation.scope, Permission.DATA_READ, now=at(0))


async def test_scope_expiry_never_exceeds_the_token() -> None:
    claims = admin_claims(expires_at=at(120))
    derivation = await mapped_deriver(directory=FakeDirectory()).derive(claims)
    assert derivation.scope.to_contract().expires_at is not None
    assert roles_of(derivation)[0][2] == _text(at(120))


def _text(value: datetime) -> str:
    return value.strftime("%Y-%m-%dT%H:%M:%SZ")


def test_constructor_rejects_wrong_types() -> None:
    with pytest.raises(TypeError):
        make_deriver(make_repo(), claim_mapping={"tenant_id": TENANT})
    with pytest.raises(TypeError):
        make_deriver(make_repo(), domain_directory=object())
    with pytest.raises(TypeError):
        make_deriver(make_repo(), claim_grant_observer=object())
