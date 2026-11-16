"""PRP-45 item 3: ``GET/PUT /api/v1/admin/system/settings`` (If-Match, diff, audit, revisions)."""

from __future__ import annotations

import pytest
from neurosphere_api.admin.system.settings_router import ABSENT_ETAG
from neurosphere_core.admin import InMemoryAdminConfigRepository
from neurosphere_core.admin.runtime import SETTING_KEYS
from system_harness import (  # pyright: ignore[reportMissingImports]
    SystemWorld,
    configure_env,
    mcp_body,
    model_body,
    scan_body,
    search_body,
    seed,
    write_target_body,
)


@pytest.fixture(autouse=True)
def _auth(monkeypatch: pytest.MonkeyPatch) -> None:
    configure_env(monkeypatch)


def test_list_has_the_six_keys_with_source_and_revisions(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NS_SEARCH_PROVIDER", "fixture")
    repository = InMemoryAdminConfigRepository(cloud="commercial")
    seed(repository, "copilot", model_body())
    world = SystemWorld.build(repository=repository)
    body = world.get("/settings").json()
    items = {i["key"]: i for i in body["items"]}
    assert list(items) == list(SETTING_KEYS)
    assert items["copilot"]["source"] == "stored"
    assert items["copilot"]["stored_revision"] == items["copilot"]["applied_revision"] == 1
    assert items["copilot"]["restart_required"] is False
    assert items["search"]["source"] == "env"
    assert items["judge"]["source"] == "default"
    assert items["judge"]["etag"] == ABSENT_ETAG
    assert items["write_targets"]["applied_by_runtime"] is False
    assert body["stored_settings"]["status"] == "loaded"


def test_create_then_replace_returns_diff_revision_and_restart_required() -> None:
    world = SystemWorld.build()
    first = world.get("/settings/copilot")
    assert first.status_code == 200 and first.headers["etag"] == ABSENT_ETAG
    created = world.put("copilot", model_body(), ABSENT_ETAG)
    assert created.status_code == 200, created.text
    out = created.json()
    assert out["version"] == 1 and out["document_id"] == "system.copilot"
    assert out["stored_revision"] == 1 and out["applied_revision"] is None
    assert out["restart_required"] is True
    assert {"pointer": "/copilot/deployment", "before": None, "after": "gpt-4o"} in out["diff"]
    etag = created.headers["etag"]

    changed = world.put("copilot", model_body(deployment="gpt-4o-mini"), etag)
    assert changed.status_code == 200, changed.text
    assert changed.json()["diff"] == [
        {"pointer": "/copilot/deployment", "before": "gpt-4o", "after": "gpt-4o-mini"}
    ]
    assert changed.json()["stored_revision"] == 2
    view = world.get("/settings/copilot").json()
    assert view["entries"][0]["value"]["copilot"]["deployment"] == "gpt-4o-mini"
    assert view["source"] == "default"  # applied at the next start (A1)


def test_writes_are_audited_without_values() -> None:
    world = SystemWorld.build()
    assert world.put("scan", scan_body(), ABSENT_ETAG).status_code == 200
    records = world.records()
    assert len(records) == 2
    assert [r["kind"] for r in records] == ["before", "after"]
    assert all(r["chain_id"] == "contoso.admin-config" for r in records)
    text = str(records)
    assert "subscriptions" not in text and "0b5d0c6e" not in text


def test_missing_if_match_is_invalid_schema_and_stale_is_stale_version() -> None:
    world = SystemWorld.build()
    missing = world.put("search", search_body(), None)
    assert missing.status_code == 422
    assert missing.json()["code"] == "invalid_schema"
    assert world.put("search", search_body(), ABSENT_ETAG).status_code == 200
    again = world.put("search", search_body(), ABSENT_ETAG)
    assert again.status_code == 409 and again.json()["code"] == "stale_version"
    stale = world.put("search", search_body(), '"cfg-999"')
    assert stale.status_code == 409 and stale.json()["code"] == "stale_version"
    nothing = world.put("judge", model_body("judge"), '"cfg-1"')
    assert nothing.status_code == 409


def test_write_targets_hold_one_entry_per_kind_and_are_not_applied() -> None:
    world = SystemWorld.build()
    assert world.put("write_targets", write_target_body("apim"), ABSENT_ETAG).status_code == 200
    second = world.put("write_targets", write_target_body("foundry"), ABSENT_ETAG)
    assert second.status_code == 200
    assert second.json()["restart_required"] is False
    view = world.get("/settings/write_targets").json()
    assert [e["document_id"] for e in view["entries"]] == [
        "system.write_target.apim",
        "system.write_target.foundry",
    ]
    assert view["stored_revision"] == 2 and view["etag"] is None
    assert view["applied_by_runtime"] is False


@pytest.mark.parametrize(
    ("key", "body"),
    [
        ("judge", model_body("judge")),
        ("mcp_server", mcp_body()),
        ("scan", scan_body(enabled=False)),
        ("search", search_body()),
    ],
)
def test_every_runtime_key_can_be_stored(key: str, body: dict[str, object]) -> None:
    world = SystemWorld.build()
    response = world.put(key, body, ABSENT_ETAG)
    assert response.status_code == 200, response.text
    assert world.get(f"/settings/{key}").json()["stored_revision"] == 1


def test_unknown_key_is_422() -> None:
    world = SystemWorld.build()
    assert world.get("/settings/branding").status_code == 422
    assert world.put("branding", scan_body(), ABSENT_ETAG).status_code == 422
