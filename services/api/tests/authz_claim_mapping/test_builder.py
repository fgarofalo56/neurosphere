"""PRP-138 item 4: the authz builder composes the Entra claim role mapping.

Unset means the composition is exactly as before; every defect fails the ``authz`` component at
startup (protected routes answer 503); a valid mapping is published, handed to the deriver and
applied end to end with an audit record. No network, no cloud: in-memory stores only.
"""

from __future__ import annotations

import asyncio
import json
import os
from collections.abc import Iterable
from typing import Any

import pytest
from authz.authz_helpers import (  # pyright: ignore[reportMissingImports]
    AUDIENCE,
    BOB,
    CUSTOMER,
    TENANT,
    FakeClock,
    dev_issuer,
)
from neurosphere_api.authz import ClaimGrantAuditObserver, claim_mapping_stats
from neurosphere_api.authz.claim_audit import deriver_mapping_options
from neurosphere_api.runtime.builders import (
    AUDIT_REPOSITORY,
    CLAIM_ROLE_MAPPING,
    DOMAIN_REGISTRY,
    BuildContext,
    BuilderSpec,
)
from neurosphere_api.runtime.builders.authz import RegistryDomainDirectory
from neurosphere_api.runtime.settings import AuthSettings
from neurosphere_contracts.admin.v1.domain_definition import DomainDefinition
from neurosphere_core.admin import InMemoryAdminConfigRepository
from neurosphere_core.admin.platform import DomainAdmin, DomainRegistry
from neurosphere_core.audit import AuditRepository, InMemoryAuditStore
from neurosphere_core.audit.chains import domain_audit_chain_id
from neurosphere_core.auth.scope import (
    ClaimRoleMapping,
    ScopeDeriver,
    customer_control_domain_id,
)
from neurosphere_core.cloud import CloudName, Settings
from neurosphere_core.errors import DependencyTransientError
from runtime_api.runtime_helpers import (  # pyright: ignore[reportMissingImports]
    Composed,
    builders_with_stubs,
    compose,
    configure_auth_env,
    configured_overrides,
)

ME = "/api/v1/me/domains"
OTHER_TENANT = "11111111-2222-4333-8444-555555555555"
CONTROL = customer_control_domain_id("commercial", CUSTOMER)
HR = "commercial:contoso:catalog:domain:hr"
SALES = "commercial:contoso:catalog:domain:sales"
GROUP = "3f2504e0-4f89-41d3-9a0c-0305e82c3301"
ACTOR = "commercial:contoso:entra:person:p-" + "0c" * 32

_PREFIXES = ("NS_AUTH_", "NS_STORE_", "NS_CORS_", "NS_COSMOS_", "NS_REVOCATION_", "NS_COPILOT_")
_NAMES = ("NS_CLOUD", "NS_INGEST_PRODUCERS_FILE", "NS_SCAN_ENABLED", "NS_MCP_RESOURCE_SERVER_URL")


@pytest.fixture(autouse=True)
def _clean_composition_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Same isolation as ``runtime_api/conftest.py``: no composition settings leak in."""
    for name in sorted(os.environ):
        if name.startswith(_PREFIXES) or name in _NAMES:
            monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("NS_ENV", "local")


def _entry(**values: Any) -> dict[str, Any]:
    return {
        "id": "ns-admins",
        "claim": "roles",
        "value": "admin",
        "role": "admin",
        "domains": "all",
        "customer_control": True,
        **values,
    }


def _mapping(*entries: dict[str, Any], **top: Any) -> str:
    doc: dict[str, Any] = {
        "tenant_id": TENANT,
        "audience": AUDIENCE,
        "entries": list(entries) or [_entry()],
        **top,
    }
    return json.dumps(doc)


class _Captured:
    def __init__(self) -> None:
        self.mapping: ClaimRoleMapping | None = None
        self.registry_seen_by_authz: DomainRegistry | None = None


def _probe(captured: _Captured, audit: AuditRepository | None) -> BuilderSpec:
    """Runs right after authz: records what authz published and stands in for the data builder's
    ``AUDIT_REPOSITORY`` (the data builder is stubbed in these tests)."""

    def build(ctx: BuildContext) -> None:
        captured.mapping = ctx.maybe_shared(CLAIM_ROLE_MAPPING)
        captured.registry_seen_by_authz = ctx.maybe_shared(DOMAIN_REGISTRY)
        if audit is not None:
            ctx.publish(AUDIT_REPOSITORY, audit)

    return BuilderSpec("probe", (), build)


def _builders(captured: _Captured, audit: AuditRepository | None) -> tuple[BuilderSpec, ...]:
    stubs = builders_with_stubs()
    return (stubs[0], _probe(captured, audit), *stubs[1:])


def _compose(
    *,
    audit: AuditRepository | None = None,
    admin_config: InMemoryAdminConfigRepository | None = None,
    builders: Iterable[BuilderSpec] | None = None,
    settings: Settings | None = None,
) -> tuple[Composed, _Captured]:
    captured = _Captured()
    clock = FakeClock()
    backends: dict[str, object] = {}
    if admin_config is not None:
        backends["admin_config_repository"] = admin_config
    overrides = configured_overrides(clock, backends=backends)
    composed = compose(
        overrides,
        builders=builders if builders is not None else _builders(captured, audit),
        clock=clock,
        settings=settings,
    )
    return composed, captured


def _readiness(composed: Composed) -> list[tuple[str, str, str | None, bool]]:
    return [(s.name, s.state, s.reason, s.required) for s in composed.registry.snapshot()]


def _deriver(composed: Composed) -> ScopeDeriver:
    deriver = composed.app.state.authz.scope_source
    assert isinstance(deriver, ScopeDeriver)
    return deriver


def _mapped_auth(composed: Composed, object_id: str = BOB, **mint: Any) -> dict[str, str]:
    mint.setdefault("roles", ["admin"])
    mint.setdefault("scopes", ["access_as_user"])
    token = dev_issuer().mint(
        audience=AUDIENCE, object_id=object_id, now=composed.clock.now, **mint
    )
    return {"Authorization": f"Bearer {token}"}


async def _register(repository: InMemoryAdminConfigRepository, domain_id: str) -> None:
    await DomainAdmin(repository, cloud="commercial").create(
        CUSTOMER,
        DomainDefinition.model_validate(
            {
                "schema_version": "1.0.0",
                "domain_id": domain_id,
                "display_name": "D",
                "classification": "internal",
                "residency_region": "eastus2",
                "status": "active",
                "is_control_domain": False,
            }
        ),
        updated_by=ACTOR,
    )


# --------------------------------------------------------------------------- unset = unchanged


def test_setting_is_read_from_ns_auth_role_mappings(monkeypatch: pytest.MonkeyPatch) -> None:
    assert AuthSettings().role_mappings is None
    monkeypatch.setenv("NS_AUTH_ROLE_MAPPINGS", _mapping())
    assert AuthSettings().role_mappings == _mapping()


@pytest.mark.parametrize("value", [None, "", "   "])
def test_unset_or_blank_setting_composes_exactly_as_without_it(
    monkeypatch: pytest.MonkeyPatch, value: str | None
) -> None:
    configure_auth_env(monkeypatch)
    baseline, _ = _compose()
    if value is not None:
        monkeypatch.setenv("NS_AUTH_ROLE_MAPPINGS", value)
    composed, captured = _compose()
    assert composed.registry.components == baseline.registry.components
    assert _readiness(composed) == _readiness(baseline)
    assert composed.registry.get("authz").state == "ok"
    assert captured.mapping is None
    assert claim_mapping_stats(composed.app.state) is None
    deriver = _deriver(composed)
    # The deriver was built with its defaults: no mapping, directory, observer or dev issuer.
    assert deriver._claim_mapping is None  # pyright: ignore[reportPrivateUsage]
    assert deriver._directory is None  # pyright: ignore[reportPrivateUsage]
    assert deriver._observer is None  # pyright: ignore[reportPrivateUsage]
    assert deriver._allow_dev_issuer is False  # pyright: ignore[reportPrivateUsage]
    assert deriver_mapping_options(None, domain_directory=None, observer=None, env="local") == {}


def test_unset_mapping_ignores_role_claims(monkeypatch: pytest.MonkeyPatch) -> None:
    configure_auth_env(monkeypatch)
    audit = AuditRepository(InMemoryAuditStore())
    composed, _ = _compose(audit=audit)
    with composed.client() as client:
        response = client.get(ME, headers=_mapped_auth(composed))
    # BOB holds nothing in the policy store and the role claim is not authority: 403.
    assert response.status_code == 403, response.text
    assert response.json()["reason"] == "permission_missing"
    assert response.json()["detail"] == "this operation needs `data.read`"
    chain = domain_audit_chain_id(CUSTOMER, CONTROL)
    assert asyncio.run(audit.read_range(chain, limit=10)) == []


# --------------------------------------------------------------------------- valid mapping


def test_valid_mapping_is_published_and_passed_to_the_deriver(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configure_auth_env(monkeypatch)
    baseline, _ = _compose()
    monkeypatch.setenv("NS_AUTH_ROLE_MAPPINGS", _mapping())
    composed, captured = _compose()
    assert _readiness(composed) == _readiness(baseline)  # same components, same readiness
    assert isinstance(captured.mapping, ClaimRoleMapping)
    assert [e.id for e in captured.mapping.entries] == ["ns-admins"]
    assert captured.registry_seen_by_authz is None  # admin_platform has not run yet
    deriver = _deriver(composed)
    assert deriver._claim_mapping is captured.mapping  # pyright: ignore[reportPrivateUsage]
    assert isinstance(deriver._directory, RegistryDomainDirectory)  # pyright: ignore[reportPrivateUsage]
    assert isinstance(deriver._observer, ClaimGrantAuditObserver)  # pyright: ignore[reportPrivateUsage]
    assert deriver._allow_dev_issuer is True  # pyright: ignore[reportPrivateUsage]
    assert claim_mapping_stats(composed.app.state) is not None


def test_mapped_token_is_applied_and_audited_end_to_end(monkeypatch: pytest.MonkeyPatch) -> None:
    configure_auth_env(monkeypatch)
    monkeypatch.setenv("NS_AUTH_ROLE_MAPPINGS", _mapping())
    audit = AuditRepository(InMemoryAuditStore())
    admin_config = InMemoryAdminConfigRepository(cloud="commercial")
    asyncio.run(_register(admin_config, HR))
    composed, _ = _compose(audit=audit, admin_config=admin_config)
    assert composed.registry.get("admin_platform").state == "ok"
    with composed.client() as client:
        headers = _mapped_auth(composed)
        first = client.get(ME, headers=headers)
        second = client.get(ME, headers=headers)
        asyncio.run(_register(admin_config, SALES))  # a later domain: no configuration change
        third = client.get(ME, headers=headers)
    assert first.status_code == 200, first.text
    assert {item["domain_id"] for item in first.json()["items"]} >= {HR}
    assert second.status_code == 200
    assert third.status_code == 200
    chain = domain_audit_chain_id(CUSTOMER, CONTROL)
    records = asyncio.run(audit.read_range(chain, limit=10))
    assert len(records) == 1  # once per token
    assert records[0].operation == "identity.claim_role_applied"
    stats = claim_mapping_stats(composed.app.state)
    assert stats is not None
    assert stats.snapshot()["applied"] == 3


def test_missing_audit_repository_answers_503(monkeypatch: pytest.MonkeyPatch) -> None:
    configure_auth_env(monkeypatch)
    monkeypatch.setenv("NS_AUTH_ROLE_MAPPINGS", _mapping())
    composed, _ = _compose(audit=None)  # data builder stubbed: no AUDIT_REPOSITORY published
    with composed.client() as client:
        response = client.get(ME, headers=_mapped_auth(composed))
        unmapped = client.get(ME, headers=_mapped_auth(composed, roles=["reader"]))
    assert response.status_code == 503
    assert response.json()["reason"] == "audit_write_failed"
    assert unmapped.status_code == 403  # no grant, nothing to audit: an ordinary denial
    assert unmapped.json()["reason"] == "permission_missing"


def test_overage_and_unmatched_values_are_counted(monkeypatch: pytest.MonkeyPatch) -> None:
    configure_auth_env(monkeypatch)
    group_entry = _entry(id="ns-group", claim="groups", value=GROUP, role="viewer", domains=[HR])
    monkeypatch.setenv("NS_AUTH_ROLE_MAPPINGS", _mapping(_entry(), group_entry))
    audit = AuditRepository(InMemoryAuditStore())
    composed, _ = _compose(audit=audit)
    with composed.client() as client:
        client.get(ME, headers=_mapped_auth(composed, roles=["reader"], extra={"hasgroups": True}))
    stats = claim_mapping_stats(composed.app.state)
    assert stats is not None
    assert stats.snapshot() == {"groups_overage": 1, "unmatched_values": 1}


# --------------------------------------------------------------------------- startup refusals

_FOREIGN_CLOUD = "government:contoso:catalog:domain:finance"
_FOREIGN_CUSTOMER = "commercial:fabrikam:catalog:domain:finance"

REFUSALS: list[tuple[str, str, str]] = [
    ("malformed_json", "{not json", "role_mapping_invalid"),
    ("unknown_role", _mapping(_entry(role="superuser")), "role_mapping_invalid"),
    ("duplicate_entry_id", _mapping(_entry(), _entry(value="other")), "role_mapping_invalid"),
    (
        "value_to_two_roles",
        _mapping(_entry(), _entry(id="ns-viewers", role="viewer")),
        "role_mapping_invalid",
    ),
    (
        "non_guid_group",
        _mapping(_entry(claim="groups", value="NeuroSphere Admins")),
        "role_mapping_invalid",
    ),
    ("foreign_cloud_domain", _mapping(_entry(domains=[_FOREIGN_CLOUD])), "role_mapping_invalid"),
    (
        "foreign_customer_domain",
        _mapping(_entry(domains=[_FOREIGN_CUSTOMER])),
        "role_mapping_invalid",
    ),
    (
        "one_foreign_domain_among_owned",
        _mapping(_entry(domains=[HR, _FOREIGN_CUSTOMER])),
        "role_mapping_invalid",
    ),
    ("wrong_tenant", _mapping(tenant_id=OTHER_TENANT), "role_mapping_binding_mismatch"),
    ("wrong_audience", _mapping(audience="api://another-api"), "role_mapping_binding_mismatch"),
]


@pytest.mark.parametrize(("case", "raw", "reason"), REFUSALS, ids=[c[0] for c in REFUSALS])
def test_defective_mapping_fails_authz_at_startup_and_routes_answer_503(
    monkeypatch: pytest.MonkeyPatch, case: str, raw: str, reason: str
) -> None:
    configure_auth_env(monkeypatch)
    monkeypatch.setenv("NS_AUTH_ROLE_MAPPINGS", raw)
    composed, captured = _compose()
    status = composed.registry.get("authz")
    assert (status.state, status.reason) == ("failed", reason)
    assert captured.mapping is None
    assert not hasattr(composed.app.state, "authz")
    with composed.client() as client:
        response = client.get(ME, headers=_mapped_auth(composed))
    assert response.status_code == 503
    assert response.json()["reason"] == "authz_unconfigured"
    assert raw not in response.text


def test_tenant_is_compared_normalised(monkeypatch: pytest.MonkeyPatch) -> None:
    configure_auth_env(monkeypatch, TENANT_ID=TENANT.upper())
    monkeypatch.setenv("NS_AUTH_ROLE_MAPPINGS", _mapping(tenant_id=TENANT.upper()))
    composed, captured = _compose()
    assert composed.registry.get("authz").state == "ok"
    assert captured.mapping is not None
    assert captured.mapping.tenant_id == TENANT


def test_audience_may_be_any_configured_audience(monkeypatch: pytest.MonkeyPatch) -> None:
    second = "api://neurosphere-second"
    configure_auth_env(monkeypatch, AUDIENCES=f"{AUDIENCE},{second}")
    monkeypatch.setenv("NS_AUTH_ROLE_MAPPINGS", _mapping(audience=second))
    composed, captured = _compose()
    assert composed.registry.get("authz").state == "ok"
    assert captured.mapping is not None


# --------------------------------------------------------------------------- dev issuer


@pytest.mark.parametrize(
    ("env", "allowed"),
    [("local", True), ("dev", False), ("test", False), ("staging", False), ("prod", False)],
)
def test_local_issuer_is_mappable_only_in_local(env: str, allowed: bool) -> None:
    from neurosphere_core.auth.scope import parse_claim_role_mapping

    mapping = parse_claim_role_mapping(_mapping())
    options = deriver_mapping_options(mapping, domain_directory=None, observer=None, env=env)
    assert options["allow_dev_issuer"] is allowed


def test_outside_local_the_composed_deriver_refuses_the_local_issuer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "neurosphere_api.runtime.compose.refuse_overrides_outside_local", lambda *_: None
    )
    configure_auth_env(monkeypatch, PSEUDONYM_KEY="k" * 40)
    monkeypatch.setenv(
        "NS_AUTH_PSEUDONYM_KEY_REFERENCE", "https://ns-test-kv.vault.azure.net/secrets/pseudonym"
    )
    monkeypatch.setenv("NS_AUTH_ROLE_MAPPINGS", _mapping())
    settings = Settings(env="dev", cloud=CloudName.COMMERCIAL)
    composed, captured = _compose(settings=settings)
    assert composed.registry.get("authz").state == "ok"
    assert captured.mapping is not None
    assert _deriver(composed)._allow_dev_issuer is False  # pyright: ignore[reportPrivateUsage]


# --------------------------------------------------------------------------- directory


def _registry_with(*domains: str) -> DomainRegistry:
    repository = InMemoryAdminConfigRepository(cloud="commercial")
    for domain in domains:
        asyncio.run(_register(repository, domain))
    return DomainRegistry(repository)


def test_directory_resolves_the_registry_on_every_call() -> None:
    holder: dict[str, DomainRegistry] = {}
    directory = RegistryDomainDirectory(lambda: holder.get("registry"), cloud="commercial")
    with pytest.raises(DependencyTransientError) as caught:
        asyncio.run(directory.active_domain_ids(CUSTOMER))
    assert caught.value.reason == "domain_directory_unavailable"
    holder["registry"] = _registry_with(HR)
    assert asyncio.run(directory.active_domain_ids(CUSTOMER)) == (HR,)
    holder["registry"] = _registry_with(HR, SALES)
    assert sorted(asyncio.run(directory.active_domain_ids(CUSTOMER))) == [HR, SALES]


def test_directory_leaves_out_the_control_domain_and_retired_domains() -> None:
    repository = InMemoryAdminConfigRepository(cloud="commercial")
    asyncio.run(_register(repository, HR))
    asyncio.run(_register(repository, SALES))
    admin = DomainAdmin(repository, cloud="commercial")
    current = asyncio.run(admin.get(CUSTOMER, SALES))
    assert current is not None
    asyncio.run(admin.retire(CUSTOMER, SALES, if_match=current.etag.root, updated_by=ACTOR))
    directory = RegistryDomainDirectory(lambda: DomainRegistry(repository), cloud="commercial")
    assert asyncio.run(directory.active_domain_ids(CUSTOMER)) == (HR,)


def test_unpublished_registry_denies_a_mapped_all_domains_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configure_auth_env(monkeypatch)
    monkeypatch.setenv("NS_AUTH_ROLE_MAPPINGS", _mapping())
    audit = AuditRepository(InMemoryAuditStore())
    captured = _Captured()
    # authz + the probe only: admin_platform never runs, so DOMAIN_REGISTRY is never published.
    builders = (builders_with_stubs()[0], _probe(captured, audit))
    composed, _ = _compose(builders=builders)
    assert composed.registry.get("authz").state == "ok"
    with composed.client() as client:
        response = client.get(ME, headers=_mapped_auth(composed))
    assert response.status_code == 503
    assert response.json()["reason"] == "domain_directory_unavailable"
