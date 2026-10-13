"""Scope derivation: inputs are VerifiedClaims + policy store only; every failure denies."""

from __future__ import annotations

import ast
import asyncio
import inspect
import json
import random
import string
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest
from neurosphere_contracts.scope.v1.identity_scope import IdentityScope as ContractScope
from neurosphere_core.auth.scope import (
    NO_POLICY_VERSION,
    InMemoryPolicyRepository,
    NoRevocationCheck,
    PolicyHead,
    PrincipalPolicy,
    Role,
    ScopeDerivationConfig,
    ScopeDeriver,
    compute_scope_hash,
    principal_document_id,
)
from neurosphere_core.cloud import CloudName
from neurosphere_core.errors import DependencyTransientError, ForbiddenError, UnauthorizedError
from neurosphere_core.scope import IdentityScope

from .scope_helpers import (
    AGENT,
    CUSTOMER,
    FINANCE,
    OBJECT_ID,
    OPERATIONS,
    OTHER_CUSTOMER_FINANCE,
    OTHER_TENANT,
    TENANT,
    FakeClock,
    at,
    grant,
    make_claims,
    make_deriver,
    make_repo,
    principal_id_for,
    principal_policy,
    pseudonymizer,
    role,
)

_SCOPE_PKG = Path(__file__).resolve().parents[3] / "neurosphere_core" / "auth" / "scope"
_EXAMPLES = (
    Path(__file__).resolve().parents[4] / "contracts" / "schemas" / "scope" / "v1" / "examples"
)


def _analyst_policy() -> PrincipalPolicy:
    return principal_policy(
        roles=(role(Role.ANALYST, FINANCE, OPERATIONS),),
        grants=(grant(AGENT, "read", "propose_action"),),
    )


def _dump(scope: IdentityScope) -> dict[str, Any]:
    return scope.to_contract().model_dump(mode="json", exclude_none=True)


# ------------------------------------------------------------------ happy path and contract


async def test_derives_contract_scope_from_claims_and_policy() -> None:
    deriver = make_deriver(make_repo(_analyst_policy()))
    scope = await deriver.from_verified_claims(make_claims())

    assert isinstance(scope, IdentityScope)
    doc = _dump(scope)
    ContractScope.model_validate(doc)
    assert doc["cloud"] == "commercial"
    assert doc["customer_id"] == CUSTOMER
    assert doc["principal"]["principal_id"] == principal_id_for()
    assert doc["principal"]["principal_kind"] == "user"
    assert doc["allowed_domains"] == sorted([FINANCE, OPERATIONS])
    assert doc["roles"] == [{"role": "analyst", "domain_ids": sorted([FINANCE, OPERATIONS])}]
    assert [r["resource_id"] for r in doc["allowed_resources"]] == [AGENT]
    assert doc["policy_version"] == "2026.10.01-1"
    assert doc["derived_at"] == "2027-01-15T08:00:00Z"
    assert doc["scope_hash"] == compute_scope_hash(doc)


async def test_derive_reports_assignment_and_grant_ids() -> None:
    derivation = await make_deriver(make_repo(_analyst_policy())).derive(make_claims())
    assert derivation.assignment_ids == ("ra-analyst-2",)
    assert derivation.grant_ids == ("g-1",)


@pytest.mark.parametrize("name", ["identity-scope.viewer.json", "identity-scope.scoped-admin.json"])
def test_scope_hash_matches_contract_examples(name: str) -> None:
    doc = json.loads((_EXAMPLES / "valid" / name).read_text(encoding="utf-8"))
    assert compute_scope_hash(doc) == doc["scope_hash"]


async def test_app_token_maps_to_service_principal() -> None:
    policy = principal_policy(roles=(role(Role.VIEWER, FINANCE),), kind="principal")
    scope = await make_deriver(make_repo(policy)).from_verified_claims(
        make_claims(identity_type="app")
    )
    principal = _dump(scope)["principal"]
    assert principal["principal_kind"] == "service_principal"
    assert ":entra:principal:" in principal["principal_id"]
    assert scope.allowed_domains == (FINANCE,)


async def test_scope_hash_is_stable_across_store_ordering() -> None:
    a = principal_policy(roles=(role(Role.VIEWER, OPERATIONS, FINANCE),))
    b = principal_policy(
        memberships=(OPERATIONS, FINANCE), roles=(role(Role.VIEWER, FINANCE, OPERATIONS),)
    )
    first = await make_deriver(make_repo(a)).from_verified_claims(make_claims())
    second = await make_deriver(make_repo(b)).from_verified_claims(make_claims())
    assert first.scope_hash == second.scope_hash


async def test_scope_expiry_is_capped_by_token_and_ttl() -> None:
    deriver = make_deriver(make_repo(principal_policy(roles=(role(Role.VIEWER, FINANCE),))))
    short = await deriver.from_verified_claims(make_claims(lifetime_seconds=120))
    assert _dump(short)["expires_at"] == "2027-01-15T08:02:00Z"
    long = await deriver.from_verified_claims(make_claims(lifetime_seconds=7200))
    assert _dump(long)["expires_at"] == "2027-01-15T08:05:00Z"  # default 300 s


# ------------------------------------------------------------------ deny paths


async def test_missing_principal_document_yields_empty_scope() -> None:
    scope = await make_deriver(make_repo(None)).from_verified_claims(make_claims())
    doc = _dump(scope)
    assert doc["roles"] == []
    assert doc["allowed_domains"] == []
    assert doc["allowed_resources"] == []


async def test_missing_policy_head_yields_empty_scope_and_skips_principal_read() -> None:
    repo = make_repo(_analyst_policy(), version=None)
    scope = await make_deriver(repo).from_verified_claims(make_claims())
    assert scope.policy_version == NO_POLICY_VERSION
    assert scope.allowed_domains == ()
    assert repo.principal_reads == 0


@pytest.mark.parametrize(
    "error",
    [
        RuntimeError("boom"),
        ConnectionError("reset"),
        TimeoutError(),
        ForbiddenError("store said 403"),
        DependencyTransientError("down"),
    ],
)
async def test_store_error_raises_dependency_transient_never_empty_scope(
    error: BaseException,
) -> None:
    repo = make_repo(_analyst_policy())
    repo.fail_with(error)
    with pytest.raises(DependencyTransientError) as info:
        await make_deriver(repo).from_verified_claims(make_claims())
    assert info.value.status == 503


async def test_store_error_on_principal_read_raises_dependency_transient() -> None:
    class HeadOnly(InMemoryPolicyRepository):
        async def get_principal_policy(self, customer_id: str, principal_id: str) -> None:
            raise OSError("socket closed")

    repo = HeadOnly()
    repo.put_head(PolicyHead(customer_id=CUSTOMER, policy_version="v1"))
    with pytest.raises(DependencyTransientError):
        await make_deriver(repo).from_verified_claims(make_claims())


async def test_store_timeout_raises_dependency_transient() -> None:
    class Hanging(InMemoryPolicyRepository):
        async def get_policy_head(self, customer_id: str) -> PolicyHead | None:
            await asyncio.Event().wait()
            return None

    with pytest.raises(DependencyTransientError) as info:
        await make_deriver(Hanging(), store_timeout_seconds=0.01).from_verified_claims(
            make_claims()
        )
    assert info.value.reason == "policy_store_unavailable"


async def test_document_for_another_principal_is_upstream_invalid() -> None:
    class Confused(InMemoryPolicyRepository):
        async def get_principal_policy(
            self, customer_id: str, principal_id: str
        ) -> PrincipalPolicy | None:
            other = principal_id_for("11111111-2222-4333-8444-555555555555")
            return principal_policy(
                roles=(role(Role.ADMIN, FINANCE, expires_in=600),),
                object_id="11111111-2222-4333-8444-555555555555",
            ).model_copy(update={"id": principal_document_id(other)})

    repo = Confused()
    repo.put_head(PolicyHead(customer_id=CUSTOMER, policy_version="v1"))
    with pytest.raises(DependencyTransientError) as info:
        await make_deriver(repo).from_verified_claims(make_claims())
    assert info.value.status == 502


@pytest.mark.parametrize(
    ("claims_kwargs", "reason"),
    [
        ({"cloud": CloudName.GOVERNMENT}, "cloud"),
        ({"tenant_id": OTHER_TENANT}, "tenant"),
        ({"lifetime_seconds": -1}, "expired"),
    ],
)
async def test_binding_mismatch_is_unauthorized(claims_kwargs: dict[str, Any], reason: str) -> None:
    repo = make_repo(_analyst_policy())
    with pytest.raises(UnauthorizedError) as info:
        await make_deriver(repo).from_verified_claims(make_claims(**claims_kwargs))
    assert info.value.reason == reason
    assert repo.head_reads == 0


# ------------------------------------------------------------------ policy cache (C14)


async def test_cache_serves_within_ttl_and_fails_closed_after_expiry() -> None:
    clock = FakeClock()
    repo = make_repo(_analyst_policy())
    deriver = make_deriver(repo, clock=clock, policy_cache_ttl_seconds=30)
    baseline = await deriver.from_verified_claims(make_claims())
    assert (repo.head_reads, repo.principal_reads) == (1, 1)

    repo.fail_with(ConnectionError("store down"))
    clock.advance(29)
    stale = await deriver.from_verified_claims(make_claims())
    assert stale.scope_hash == baseline.scope_hash  # stale but unexpired may serve
    assert (repo.head_reads, repo.principal_reads) == (1, 1)

    clock.advance(1)  # now == expiry
    with pytest.raises(DependencyTransientError):
        await deriver.from_verified_claims(make_claims())
    clock.advance(0.5)
    with pytest.raises(DependencyTransientError):  # expiry was not extended by the error
        await deriver.from_verified_claims(make_claims())

    repo.fail_with(None)
    recovered = await deriver.from_verified_claims(make_claims())
    assert recovered.scope_hash == baseline.scope_hash


async def test_policy_version_bump_rereads_principal_document() -> None:
    clock = FakeClock()
    repo = make_repo(principal_policy(roles=(role(Role.VIEWER, FINANCE),)))
    deriver = make_deriver(repo, clock=clock, policy_cache_ttl_seconds=10)
    first = await deriver.from_verified_claims(make_claims())

    repo.put_head(PolicyHead(customer_id=CUSTOMER, policy_version="2026.10.01-2"))
    repo.put_principal(principal_policy(roles=(role(Role.VIEWER, OPERATIONS),)))
    clock.advance(10)
    second = await deriver.from_verified_claims(make_claims())
    assert second.policy_version == "2026.10.01-2"
    assert second.allowed_domains == (OPERATIONS,)
    assert first.scope_hash != second.scope_hash


async def test_invalidate_principal_forces_reread() -> None:
    repo = make_repo(_analyst_policy())
    deriver = make_deriver(repo)
    await deriver.from_verified_claims(make_claims())
    assert deriver.invalidate_principal(principal_id_for()) == 1
    repo.remove_principal(CUSTOMER, principal_id_for())
    scope = await deriver.from_verified_claims(make_claims())
    assert scope.allowed_domains == ()


# ------------------------------------------------------------------ revocation hook


class _Checker:
    def __init__(self, answer: object = False, error: BaseException | None = None) -> None:
        self.answer = answer
        self.error = error
        self.calls: list[tuple[str, datetime]] = []

    async def is_revoked(self, principal_id: str, issued_at: datetime) -> bool:
        self.calls.append((principal_id, issued_at))
        if self.error is not None:
            raise self.error
        return self.answer  # type: ignore[return-value]


async def test_revocation_checker_receives_pseudonymous_id_before_policy_read() -> None:
    checker = _Checker(answer=True)
    repo = make_repo(_analyst_policy())
    with pytest.raises(ForbiddenError) as info:
        await make_deriver(repo, revocation_checker=checker).from_verified_claims(make_claims())
    assert info.value.reason == "principal_revoked"
    assert checker.calls == [(principal_id_for(), at(-60))]
    assert OBJECT_ID not in checker.calls[0][0]
    assert repo.head_reads == 0


async def test_revocation_dependency_transient_propagates_unchanged() -> None:
    error = DependencyTransientError("revocation store down")
    checker = _Checker(error=error)
    with pytest.raises(DependencyTransientError) as info:
        await make_deriver(
            make_repo(_analyst_policy()), revocation_checker=checker
        ).from_verified_claims(make_claims())
    assert info.value is error


@pytest.mark.parametrize(
    "checker", [_Checker(error=RuntimeError("bug")), _Checker(answer=None), _Checker(answer=1)]
)
async def test_revocation_failure_or_non_bool_fails_closed(checker: _Checker) -> None:
    with pytest.raises(DependencyTransientError):
        await make_deriver(
            make_repo(_analyst_policy()), revocation_checker=checker
        ).from_verified_claims(make_claims())


async def test_not_revoked_derives_normally() -> None:
    scope = await make_deriver(
        make_repo(_analyst_policy()), revocation_checker=_Checker(False)
    ).from_verified_claims(make_claims())
    assert scope.allowed_domains == tuple(sorted([FINANCE, OPERATIONS]))


# ------------------------------------------------------------------ caller input never counts


def test_derivation_api_accepts_only_verified_claims() -> None:
    for method in (ScopeDeriver.from_verified_claims, ScopeDeriver.derive):
        params = list(inspect.signature(method).parameters)
        assert params == ["self", "claims"]
    init_params = set(inspect.signature(ScopeDeriver.__init__).parameters)
    assert init_params == {
        "self",
        "config",
        "policy_repository",
        "pseudonymizer",
        "revocation_checker",
        "clock",
    }


class _FakeRequest:
    def __init__(self, forged: dict[str, Any]) -> None:
        self.headers = {"x-domain-id": forged["domain_id"], "x-customer-id": forged["customer_id"]}
        self.query_params = dict(forged)
        self.cookies = {"domain_id": forged["domain_id"]}
        self.body = json.dumps(forged).encode()


async def test_request_objects_and_dicts_are_refused() -> None:
    deriver = make_deriver(make_repo(_analyst_policy()))
    forged = {"domain_id": OTHER_CUSTOMER_FINANCE, "customer_id": "fabrikam"}
    claims_dict = make_claims().model_dump()
    for bogus in (_FakeRequest(forged), claims_dict, {**claims_dict, **forged}):
        with pytest.raises(TypeError):
            await deriver.from_verified_claims(bogus)  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        await deriver.from_verified_claims(make_claims(), request=_FakeRequest(forged))  # type: ignore[call-arg]


def _forged_value(rng: random.Random) -> str:
    choices = [
        OTHER_CUSTOMER_FINANCE,
        "commercial:contoso:catalog:domain:hr",
        "government:contoso:catalog:domain:finance",
        "commercial:contoso:catalog:domain:*",
        "fabrikam",
        "*",
        "admin",
        "security_auditor",
        "".join(
            rng.choices(string.ascii_lowercase + string.digits + ":._-*", k=rng.randint(1, 40))
        ),
    ]
    return rng.choice(choices)


async def test_fuzz_forged_caller_inputs_never_change_scope() -> None:
    """Property: forged domain/customer values in header, query, body, cookie and in
    non-authoritative claim lists (roles, groups, scopes) never change the derived scope."""
    clock = FakeClock()
    deriver = make_deriver(make_repo(_analyst_policy()), clock=clock)
    baseline = _dump(await deriver.from_verified_claims(make_claims()))
    rng = random.Random(20261012)  # noqa: S311 - deterministic fuzz corpus, not crypto
    for _ in range(300):
        forged = {"domain_id": _forged_value(rng), "customer_id": _forged_value(rng)}
        request = _FakeRequest(forged)  # what a route would see; it has no path into derivation
        assert request.headers["x-domain-id"] == forged["domain_id"]
        claims = make_claims(
            roles=tuple(_forged_value(rng) for _ in range(rng.randint(0, 4))),
            groups=tuple(_forged_value(rng) for _ in range(rng.randint(0, 4))),
            scopes=tuple(_forged_value(rng) for _ in range(rng.randint(0, 4))),
        )
        assert _dump(await deriver.from_verified_claims(claims)) == baseline


def test_scope_package_never_touches_request_surfaces() -> None:
    forbidden_modules = {"fastapi", "starlette", "httpx", "requests"}
    forbidden_attrs = {"headers", "cookies", "query_params", "body", "json", "form"}
    files = sorted(_SCOPE_PKG.glob("*.py"))
    assert files
    for path in files:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                roots = {a.name.split(".")[0] for a in node.names}
                assert not roots & forbidden_modules, path.name
            elif isinstance(node, ast.ImportFrom) and node.module:
                assert node.module.split(".")[0] not in forbidden_modules, path.name
            elif isinstance(node, ast.Attribute):
                assert node.attr not in forbidden_attrs, (path.name, node.attr)


async def test_object_id_never_appears_in_scope_or_errors() -> None:
    scope = await make_deriver(make_repo(_analyst_policy())).from_verified_claims(make_claims())
    assert OBJECT_ID not in json.dumps(_dump(scope))
    assert OBJECT_ID not in repr(scope)
    repo = make_repo(_analyst_policy())
    repo.fail_with(RuntimeError("boom"))
    with pytest.raises(DependencyTransientError) as info:
        await make_deriver(repo).from_verified_claims(make_claims())
    assert OBJECT_ID not in str(info.value)


def test_revocation_checker_is_required_none_is_refused() -> None:
    for bogus in (None, object(), "checker"):
        with pytest.raises(TypeError, match="revocation_checker is required"):
            ScopeDeriver(
                ScopeDerivationConfig(
                    cloud=CloudName.COMMERCIAL, tenant_id=TENANT, customer_id=CUSTOMER
                ),
                policy_repository=make_repo(_analyst_policy()),
                pseudonymizer=pseudonymizer(),
                revocation_checker=bogus,  # type: ignore[arg-type]
            )


async def test_explicit_no_revocation_check_is_the_only_opt_out() -> None:
    deriver = make_deriver(make_repo(_analyst_policy()), revocation_checker=NoRevocationCheck())
    assert isinstance(await deriver.from_verified_claims(make_claims()), IdentityScope)
