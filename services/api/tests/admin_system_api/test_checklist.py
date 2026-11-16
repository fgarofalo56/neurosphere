"""PRP-45 item 2: ``GET /api/v1/admin/system/checklist`` and its stable item ids."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from neurosphere_api.admin.system.checklist import checklist_item_ids
from neurosphere_api.runtime.builders import BuildContext, BuilderSpec
from neurosphere_api.runtime.status import OPTIONAL_COMPONENTS, ComponentRegistry
from neurosphere_contracts.admin.v1.first_run_checklist_item import FirstRunChecklistItem
from neurosphere_core.admin import InMemoryAdminConfigRepository
from neurosphere_core.admin.runtime import StoredSettingsSnapshot
from neurosphere_core.errors import DependencyTransientError
from system_harness import (  # pyright: ignore[reportMissingImports]
    SystemWorld,
    configure_env,
    seed,
    write_target_body,
)

RUNBOOK = Path(__file__).resolve().parents[4] / "docs" / "runbooks" / "system-settings.md"


@pytest.fixture(autouse=True)
def _auth(monkeypatch: pytest.MonkeyPatch) -> None:
    configure_env(monkeypatch)


def _states(ctx: BuildContext) -> None:
    ctx.failed("copilot", "misconfigured")
    ctx.disabled("ingest")
    ctx.ok("scan")


STATES = BuilderSpec("states", ("copilot", "ingest", "scan"), _states)


def _items(world: SystemWorld) -> dict[str, dict[str, Any]]:
    response = world.get("/checklist")
    assert response.status_code == 200, response.text
    items = response.json()["items"]
    for item in items:
        FirstRunChecklistItem.model_validate(item)  # the contract shape, reason iff not complete
        assert item["doc_path"].startswith("docs/runbooks/system-settings.md#")
    return {i["item_id"]: i for i in items}


def test_one_item_per_entry_with_contract_statuses() -> None:
    items = _items(SystemWorld.build(extra=(STATES,)))
    assert list(items) == list(checklist_item_ids(ComponentRegistry()))
    assert {f"optional.{n}" for n in OPTIONAL_COMPONENTS} <= set(items)
    assert items["optional.copilot"]["status"] == "error"
    assert items["optional.copilot"]["reason"] == "misconfigured"
    assert items["optional.scan"]["status"] == "complete"
    assert items["optional.scan"]["reason"] is None
    assert items["optional.ingest"]["status"] == "disabled"
    assert items["optional.mcp_server"]["status"] == "missing"
    assert items["optional.mcp_server"]["reason"] == "not_built"
    assert items["optional.admin_system"]["status"] == "complete"
    assert items["ingest.producers"]["reason"] == "ingest_producers_unconfigured"
    assert items["write_targets.registered"]["reason"] == "write_targets_unconfigured"
    assert items["stored_settings.store"]["status"] == "complete"
    assert items["auth.customer_binding"]["status"] == "complete"
    assert items["auth.customer_binding"]["required"] is True


def test_stored_write_targets_are_listed_but_not_registered() -> None:
    repository = InMemoryAdminConfigRepository(cloud="commercial")
    seed(repository, "write_targets", write_target_body("apim"))
    item = _items(SystemWorld.build(repository=repository))["write_targets.registered"]
    assert item["status"] == "disabled"
    assert item["reason"] == "write_targets_stored_not_registered"


def test_registered_write_targets_complete_the_item() -> None:
    world = SystemWorld.build()

    class _Registry:
        def names(self) -> tuple[str, ...]:
            return ("foundry-model-swap",)

    world.composed.app.state.write_targets = _Registry()
    assert _items(world)["write_targets.registered"]["status"] == "complete"


def test_an_unreachable_store_at_startup_shows_stored_settings_unavailable() -> None:
    repository = InMemoryAdminConfigRepository(cloud="commercial")
    repository.fail_with(DependencyTransientError("down", reason="admin_config_unavailable"))
    world = SystemWorld.build(repository=repository)
    item = _items(world)["stored_settings.store"]
    assert item["status"] == "error" and item["reason"] == "stored_settings_unavailable"


def test_an_unconfigured_store_and_a_missing_binding(monkeypatch: pytest.MonkeyPatch) -> None:
    unconfigured = StoredSettingsSnapshot.empty("unconfigured", "stored_settings_unconfigured")
    world = SystemWorld.build(stored_settings=unconfigured)
    items = _items(world)
    assert items["stored_settings.store"]["status"] == "missing"
    assert items["stored_settings.store"]["reason"] == "stored_settings_unconfigured"


def test_every_item_id_is_documented_in_the_runbook() -> None:
    text = RUNBOOK.read_text(encoding="utf-8")
    for item_id in checklist_item_ids(ComponentRegistry()):
        assert f"`{item_id}`" in text, item_id
