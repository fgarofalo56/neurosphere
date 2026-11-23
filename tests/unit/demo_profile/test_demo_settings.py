"""PRP-71 item 5: the demo profile's stored feature settings (``sbx_demo_settings.py``).

No network and no Docker: the in-memory ``AdminConfigRepository`` and audit store stand in for
Cosmos. Every payload goes through the SAME write the settings PUT route runs.

Clarification 5 (decided at item 5): no write-target fake is built. The ARM host is a frozen
cloud-profile fact (``CloudProfile`` refuses a host outside the cloud's table and the ARM client
is bound to ``profile.management_url``), so it cannot be overridden under ``NS_ENV=local``. The
stored ``write_targets`` entries are therefore disabled and ``infra/dev/fakes`` does not exist.
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from neurosphere_api.admin.system.settings_router import (
    check_runtime_settings,
)
from neurosphere_core.admin import InMemoryAdminConfigRepository, admin_config_chain_id
from neurosphere_core.admin.runtime import (
    SYSTEM_SETTING_KIND,
    document_id,
    validate_setting,
)
from neurosphere_core.audit import AuditRepository
from neurosphere_core.audit.store import InMemoryAuditStore
from neurosphere_core.errors import InvalidSchemaError

SCRIPTS = Path(__file__).resolve().parents[3] / "scripts" / "sandbox"
CUSTOMER = "synthco"
ENV = {"NS_ENV": "local"}


def _load(name: str, filename: str) -> ModuleType:
    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / filename)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


settings = _load("sbx_demo_settings_under_test", "sbx_demo_settings.py")


@pytest.fixture(autouse=True)
def _local_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NS_ENV", "local")
    monkeypatch.setenv("NS_AUTH_CUSTOMER_ID", CUSTOMER)
    for name in ("NS_CLOUD", "NS_COPILOT_MODE", "NS_MCP_RESOURCE_SERVER_URL"):
        monkeypatch.delenv(name, raising=False)


def _stores() -> tuple[InMemoryAdminConfigRepository, AuditRepository]:
    return InMemoryAdminConfigRepository(cloud="commercial"), AuditRepository(InMemoryAuditStore())


def _apply(repo: Any, audit: Any, scope: Any) -> tuple[int, int]:
    return asyncio.run(settings.apply_demo_settings(repo, audit, scope, environ=ENV))


@pytest.fixture
def scope() -> Any:
    """A verified scope with a pseudonymous principal (the seed uses the workers' own)."""
    from neurosphere_contracts.scope.v1.identity_scope import IdentityScope as ContractScope
    from neurosphere_core.scope import IdentityScope

    pseudonym = "p-" + "0123456789abcdef" * 4
    contract = ContractScope.model_validate(
        {
            "schema_version": "1.0.0",
            "cloud": "commercial",
            "customer_id": CUSTOMER,
            "principal": {
                "principal_id": f"commercial:{CUSTOMER}:entra:principal:{pseudonym}",
                "principal_pseudonym": pseudonym,
                "principal_kind": "user",
            },
            "roles": [],
            "allowed_domains": [],
            "allowed_resources": [],
            "policy_version": "v1",
            "derived_at": "2026-10-10T00:00:00Z",
            "scope_hash": "sha256:" + "0" * 64,
        }
    )
    return IdentityScope._from_verified_contract(contract)  # pyright: ignore[reportPrivateUsage]


def test_every_stored_payload_validates_through_the_put_routes_checks() -> None:
    keys = [key for key, _ in settings.demo_settings()]
    assert keys == ["scan", "mcp_server", "search", "copilot", "write_targets", "write_targets"]
    for key, body in settings.demo_settings():
        model = validate_setting(key, body, customer_id=CUSTOMER, cloud="commercial")
        check_runtime_settings(key, model, "commercial")


def test_every_stored_payload_survives_the_cosmos_stores_null_dropping_write() -> None:
    """The Cosmos store writes with ``exclude_none``; the in-memory store used above does not.

    A required-but-nullable field left null is dropped on write, and the stored row then fails
    validation on every later read (the first live ``make demo-up`` hit exactly this on
    ``mcp_server``). So each payload must validate again after the dump the real store performs.
    """
    for key, body in settings.demo_settings():
        model = validate_setting(key, body, customer_id=CUSTOMER, cloud="commercial")
        stored = model.model_dump(mode="json", exclude_none=True)
        validate_setting(key, stored, customer_id=CUSTOMER, cloud="commercial")


def test_stored_values_are_non_secret_and_consistent_with_the_profile_env() -> None:
    by_key = {(k, b["setting_key"]): b for k, b in settings.demo_settings()}
    assert by_key[("mcp_server", "mcp_server")]["mcp_server"]["endpoint"] == (
        "https://127.0.0.1:8000/mcp"
    )
    assert by_key[("scan", "scan")]["enabled"] is True
    text = json.dumps(settings.demo_settings())
    assert "localhost" not in text
    for marker in ("secret", "password", "connection", "token", "AccountKey"):
        assert marker.lower() not in text.lower()


def test_recorded_mode_does_not_seed_the_copilot_or_search_rows(scope: Any) -> None:
    """A stored row beats the environment, so recorded mode leaves out copilot (disabled model)
    and search (a disabled row leaves the agent matcher without search)."""
    keys = [key for key, _ in settings.demo_settings("recorded")]
    assert keys == ["scan", "mcp_server", "write_targets", "write_targets"]
    repo, audit = _stores()
    created, skipped = asyncio.run(
        settings.apply_demo_settings(
            repo, audit, scope, environ={**ENV, "NS_DEMO_COPILOT_MODE": "recorded"}
        )
    )
    assert (created, skipped) == (4, 0)
    docs = asyncio.run(repo.list_by_kind(CUSTOMER, SYSTEM_SETTING_KIND))
    ids = {d.id.root for d in docs}
    assert document_id("copilot") not in ids
    assert document_id("search") not in ids


def test_the_copilot_placeholder_stays_disabled_for_any_other_mode() -> None:
    from neurosphere_core.admin.runtime import copilot_init_args

    copilot = {k: b for k, b in settings.demo_settings()}["copilot"]
    assert copilot["enabled"] is False
    model = validate_setting("copilot", copilot, customer_id=CUSTOMER, cloud="commercial")
    assert copilot_init_args(model, env_mode="disabled") == {"mode": "disabled"}
    # no write target and no search is enabled either (nothing local can serve them)
    for key, body in settings.demo_settings():
        if key in {"write_targets", "search"}:
            assert body["enabled"] is False


def test_a_credential_shaped_field_is_refused_by_the_validator() -> None:
    body = dict(dict(settings.demo_settings())["scan"])
    scan = dict(body["scan"])
    scan["api_key"] = "x"
    body["scan"] = scan
    with pytest.raises(InvalidSchemaError) as caught:
        validate_setting("scan", body, customer_id=CUSTOMER, cloud="commercial")
    assert caught.value.reason == "credential_in_setting"
    # and none of the payloads this script stores carries such a field name
    assert "key" not in " ".join(
        name.lower()
        for _, b in settings.demo_settings()
        for name in _names(b)
        if name != "setting_key"
    )


def _names(node: Any) -> list[str]:
    if isinstance(node, dict):
        return [str(k) for k in node] + [n for v in node.values() for n in _names(v)]
    if isinstance(node, list):
        return [n for v in node for n in _names(v)]
    return []


def test_apply_stores_every_key_then_a_second_run_changes_nothing(scope: Any) -> None:
    repo, audit = _stores()
    created, skipped = _apply(repo, audit, scope)
    assert (created, skipped) == (6, 0)

    docs = asyncio.run(repo.list_by_kind(CUSTOMER, SYSTEM_SETTING_KIND))
    assert sorted(d.id.root for d in docs) == sorted(
        [
            document_id("scan"),
            document_id("mcp_server"),
            document_id("search"),
            document_id("copilot"),
            document_id("write_targets", "apim"),
            document_id("write_targets", "foundry"),
        ]
    )
    before = {d.id.root: (d.version.root, d.etag.root) for d in docs}

    created, skipped = _apply(repo, audit, scope)
    assert (created, skipped) == (0, 6)
    after = asyncio.run(repo.list_by_kind(CUSTOMER, SYSTEM_SETTING_KIND))
    assert {d.id.root: (d.version.root, d.etag.root) for d in after} == before
    records = asyncio.run(audit.read_range(admin_config_chain_id(CUSTOMER), limit=200))
    assert len(records) == 12  # still only the first run's before/after pairs


def test_the_audit_record_is_written_per_change_without_values(scope: Any) -> None:
    repo, audit = _stores()
    _apply(repo, audit, scope)
    records = asyncio.run(audit.read_range(admin_config_chain_id(CUSTOMER), limit=200))
    assert len(records) == 12  # a before and an after record for each of the six writes
    text = json.dumps([r.model_dump(mode="json") for r in records])
    assert "system_setting.put" in text
    assert "system_setting_written" in text
    assert "https://127.0.0.1:8000/mcp" not in text  # state carries pointers, never values
    assert asyncio.run(audit.verify(admin_config_chain_id(CUSTOMER))).ok


def test_the_stored_snapshot_lists_the_keys_as_stored(scope: Any) -> None:
    from neurosphere_core.admin.runtime import load_stored_settings

    repo, audit = _stores()
    _apply(repo, audit, scope)
    snapshot = asyncio.run(load_stored_settings(repo, CUSTOMER, cloud="commercial"))
    assert snapshot.status == "loaded"
    assert not snapshot.invalid
    for key in ("scan", "mcp_server", "search", "copilot", "write_targets"):
        assert snapshot.has(key), key  # type: ignore[arg-type]
    assert len(snapshot.write_targets) == 2
    assert all(not e.setting.enabled for e in snapshot.write_targets)


def test_the_guard_refuses_a_non_loopback_endpoint_and_a_wrong_environment() -> None:
    guard_error = sys.modules["sbx_guard"].GuardError
    with pytest.raises(guard_error):
        settings.require_local({"NS_COSMOS_ENDPOINT": "https://contoso.documents.azure.com:443/"})
    with pytest.raises(settings.ConfigError):
        settings.require_local({"NS_ENV": "dev"})
    assert settings.require_local({}) == "http://127.0.0.1:8081"
    assert settings.main(["--hosted", "registration.json"], env={}) == settings.EXIT_REFUSED
    refused = settings.main([], env={"NS_COSMOS_ENDPOINT": "https://10.0.0.5:8081"})
    assert refused == settings.EXIT_REFUSED


def test_no_write_target_fake_exists_because_the_arm_host_is_not_overridable() -> None:
    from neurosphere_core.cloud.profile import CloudName, CloudProfile, profile_for

    with pytest.raises(ValueError):
        CloudProfile(
            **{**profile_for(CloudName.COMMERCIAL).model_dump(), "management_host": "127.0.0.1"}
        )
    assert not (SCRIPTS.parents[1] / "infra" / "dev" / "fakes").exists()
