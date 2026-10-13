"""Scope-hash cache keys (C9): differ across scope, cloud, customer and policy version; stable
across re-derivation and token re-issue; never contain token material or raw object ids."""

from __future__ import annotations

import inspect
import re
from typing import Any

import pytest
from neurosphere_api.authz import cache_key_prefix, scope_cache_key
from neurosphere_contracts.scope.v1.identity_scope import IdentityScope as ContractScope
from neurosphere_core.auth.scope import Role, compute_scope_hash
from neurosphere_core.scope import IdentityScope

from .authz_helpers import (
    AGENT,
    ALICE,
    BOB,
    FINANCE,
    OPERATIONS,
    TENANT,
    Harness,
    grant,
    harness,
    policy,
    role,
)

PRINCIPAL = "commercial:contoso:entra:person:p-0123456789abcdef"
KEY_SHAPE = re.compile(
    r"^ns:(commercial|government):[a-z0-9._-]+:[a-z0-9._-]+:pv=[A-Za-z0-9._%+-]+:"
    r"sha256:[0-9a-f]{64}$"
)


def make_scope(**overrides: Any) -> IdentityScope:
    doc: dict[str, Any] = {
        "schema_version": "1.0.0",
        "cloud": "commercial",
        "customer_id": "contoso",
        "principal": {
            "principal_id": PRINCIPAL,
            "principal_pseudonym": "p-0123456789abcdef",
            "principal_kind": "user",
        },
        "roles": [{"role": "viewer", "domain_ids": [FINANCE]}],
        "allowed_domains": [FINANCE],
        "allowed_resources": [],
        "policy_version": "2026.10.01-1",
        "derived_at": "2026-10-10T00:00:00Z",
    }
    doc.update(overrides)
    doc["scope_hash"] = compute_scope_hash(doc)
    contract = ContractScope.model_validate(doc)
    return IdentityScope._from_verified_contract(contract)  # pyright: ignore[reportPrivateUsage]


def _gov(value: str) -> str:
    return value.replace("commercial:", "government:", 1)


VARIANTS: dict[str, dict[str, Any]] = {
    "base": {},
    "government": {
        "cloud": "government",
        "principal": {
            "principal_id": _gov(PRINCIPAL),
            "principal_pseudonym": "p-0123456789abcdef",
            "principal_kind": "user",
        },
        "roles": [{"role": "viewer", "domain_ids": [_gov(FINANCE)]}],
        "allowed_domains": [_gov(FINANCE)],
    },
    "other_customer": {
        "customer_id": "fabrikam",
        "principal": {
            "principal_id": PRINCIPAL.replace(":contoso:", ":fabrikam:"),
            "principal_pseudonym": "p-0123456789abcdef",
            "principal_kind": "user",
        },
        "roles": [{"role": "viewer", "domain_ids": [FINANCE.replace(":contoso:", ":fabrikam:")]}],
        "allowed_domains": [FINANCE.replace(":contoso:", ":fabrikam:")],
    },
    "policy_bump": {"policy_version": "2026.10.02-1"},
    "more_domains": {
        "roles": [{"role": "viewer", "domain_ids": [FINANCE, OPERATIONS]}],
        "allowed_domains": [FINANCE, OPERATIONS],
    },
    "other_role": {"roles": [{"role": "analyst", "domain_ids": [FINANCE]}]},
    "other_principal": {
        "principal": {
            "principal_id": PRINCIPAL.replace("0123", "4567"),
            "principal_pseudonym": "p-4567456789abcdef",
            "principal_kind": "user",
        }
    },
    "grant": {
        "allowed_resources": [
            {
                "resource_id": AGENT,
                "permissions": ["read"],
                "expires_at": "2026-10-11T00:00:00Z",
            }
        ]
    },
}


def test_keys_differ_across_every_scope_dimension() -> None:
    keys = {
        name: scope_cache_key(make_scope(**v), namespace="catalog") for name, v in VARIANTS.items()
    }
    assert len(set(keys.values())) == len(keys), keys
    for key in keys.values():
        assert KEY_SHAPE.fullmatch(key), key


@pytest.mark.parametrize(
    ("variant", "prefix"),
    [
        ("base", "ns:commercial:contoso:"),
        ("government", "ns:government:contoso:"),
        ("other_customer", "ns:commercial:fabrikam:"),
        ("policy_bump", "ns:commercial:contoso:"),
    ],
)
def test_cloud_and_customer_prefix(variant: str, prefix: str) -> None:
    scope = make_scope(**VARIANTS[variant])
    assert cache_key_prefix(scope) == prefix
    key = scope_cache_key(scope, namespace="search")
    assert key.startswith(prefix + "search:pv=")
    assert key.endswith(scope.scope_hash)
    assert f"pv={scope.policy_version}:" in key


def test_namespaces_do_not_share_keys() -> None:
    scope = make_scope()
    assert scope_cache_key(scope, namespace="catalog") != scope_cache_key(scope, namespace="export")


def test_rederivation_time_does_not_change_the_key() -> None:
    first = make_scope(derived_at="2026-10-10T00:00:00Z")
    later = make_scope(derived_at="2026-10-10T00:04:00Z", expires_at="2026-10-10T00:09:00Z")
    assert scope_cache_key(first, namespace="catalog") == scope_cache_key(
        later, namespace="catalog"
    )


async def _derive(h: Harness, token: str) -> IdentityScope:
    claims = await h.validator.validate(token)
    return (await h.deriver.derive(claims)).scope


async def test_keys_from_real_tokens_hold_no_token_material() -> None:
    h = harness(
        policy(ALICE, role(Role.VIEWER, FINANCE), grants=(grant(AGENT, "read"),)),
        policy(BOB, role(Role.VIEWER, FINANCE)),
    )
    token_a = h.token(ALICE)
    h.clock.advance(5)
    token_b = h.token(ALICE, jti="second-issue")
    assert token_a != token_b
    key_a = scope_cache_key(await _derive(h, token_a), namespace="catalog")
    key_b = scope_cache_key(await _derive(h, token_b), namespace="catalog")
    key_bob = scope_cache_key(await _derive(h, h.token(BOB)), namespace="catalog")
    assert key_a == key_b  # keyed by scope, not by the token that carried it
    assert key_a != key_bob  # two principals never share a key
    for key in (key_a, key_bob):
        for token in (token_a, token_b):
            assert token not in key
            for segment in token.split("."):
                assert segment not in key
        for raw in (ALICE, BOB, TENANT):
            assert raw not in key


def test_signature_admits_no_token_parameter() -> None:
    assert list(inspect.signature(scope_cache_key).parameters) == ["scope", "namespace"]
    assert list(inspect.signature(cache_key_prefix).parameters) == ["scope"]


@pytest.mark.parametrize(
    "not_a_scope",
    ["eyJhbGciOiJSUzI1NiJ9.eyJzdWIiOiJ4In0.sig", {"scope_hash": "sha256:" + "0" * 64}, None],
)
def test_only_a_server_derived_scope_is_accepted(not_a_scope: Any) -> None:
    with pytest.raises(TypeError):
        scope_cache_key(not_a_scope, namespace="catalog")


def test_contract_object_is_not_a_scope() -> None:
    with pytest.raises(TypeError):
        scope_cache_key(make_scope().to_contract(), namespace="catalog")  # pyright: ignore[reportArgumentType]


@pytest.mark.parametrize("namespace", ["", "Catalog", "a:b", "a/b", "-a", "x" * 65, "pv=1"])
def test_namespace_cannot_forge_separators(namespace: str) -> None:
    with pytest.raises(ValueError):
        scope_cache_key(make_scope(), namespace=namespace)


def test_policy_version_is_percent_encoded() -> None:
    scope = make_scope(policy_version="v1+build.7")
    assert ":pv=v1%2Bbuild.7:" in scope_cache_key(scope, namespace="catalog")
