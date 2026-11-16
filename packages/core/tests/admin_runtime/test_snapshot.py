"""PRP-45 item 1: the stored-settings snapshot (bounded read, fallback, revisions, cache)."""

from __future__ import annotations

import asyncio
import builtins
from typing import Any

from neurosphere_contracts.admin.v1.admin_config_document import AdminConfigDocument
from neurosphere_core.admin import InMemoryAdminConfigRepository
from neurosphere_core.admin.runtime import (
    STORED_SETTINGS_UNAVAILABLE,
    SYSTEM_SETTING_KIND,
    StoredSettingsCache,
    StoredSettingsSnapshot,
    document_id,
    load_stored_settings,
    revision_of,
    run_blocking,
)
from neurosphere_core.errors import DependencyTransientError

from .setting_bodies import ACTOR, BODIES, CUSTOMER, write_target_body


async def _seed(repo: InMemoryAdminConfigRepository, key: Any, body: dict[str, Any]) -> Any:
    kind = body["write_target"]["target_kind"] if key == "write_targets" else None
    return await repo.create(
        CUSTOMER,
        SYSTEM_SETTING_KIND,
        document_id(key, kind),
        body,
        updated_by=ACTOR,  # type: ignore[arg-type]
    )


async def _load(
    repo: Any, cloud: Any = "commercial", limit_seconds: float = 2.0
) -> StoredSettingsSnapshot:
    return await load_stored_settings(repo, CUSTOMER, cloud=cloud, limit_seconds=limit_seconds)


async def test_every_key_loads_with_its_revision() -> None:
    repo = InMemoryAdminConfigRepository(cloud="commercial")
    for key, body in BODIES.items():
        await _seed(repo, key, body)
    await _seed(repo, "write_targets", write_target_body("apim"))
    snapshot = await _load(repo)
    assert snapshot.status == "loaded" and snapshot.reason is None
    for key in ("copilot", "judge", "search", "scan", "mcp_server"):
        assert snapshot.has(key)  # type: ignore[arg-type]
        assert snapshot.revision(key) == 1  # type: ignore[arg-type]
    assert [e.document_id for e in snapshot.write_targets] == [
        "system.write_target.apim",
        "system.write_target.foundry",
    ]
    assert snapshot.revision("write_targets") == 2


async def test_an_empty_store_is_loaded_and_empty() -> None:
    snapshot = await _load(InMemoryAdminConfigRepository(cloud="commercial"))
    assert snapshot.status == "loaded"
    assert not snapshot.has("copilot") and snapshot.revision("write_targets") is None


async def test_a_store_outage_yields_the_empty_unavailable_snapshot() -> None:
    repo = InMemoryAdminConfigRepository(cloud="commercial")
    await _seed(repo, "copilot", BODIES["copilot"])
    repo.fail_with(DependencyTransientError("down", reason="admin_config_unavailable"))
    snapshot = await _load(repo)
    assert snapshot.status == "unavailable"
    assert snapshot.reason == STORED_SETTINGS_UNAVAILABLE
    assert not snapshot.has("copilot")


class _Hanging(InMemoryAdminConfigRepository):
    async def list_by_kind(self, *args: Any, **kwargs: Any) -> builtins.list[AdminConfigDocument]:
        await asyncio.sleep(30)
        return []


async def test_a_timeout_yields_the_empty_unavailable_snapshot() -> None:
    snapshot = await _load(_Hanging(cloud="commercial"), limit_seconds=0.05)
    assert snapshot.status == "unavailable" and snapshot.reason == STORED_SETTINGS_UNAVAILABLE


async def test_a_document_invalid_for_this_cloud_is_skipped_and_named() -> None:
    repo = InMemoryAdminConfigRepository()  # no cloud bound: the write cannot check it
    await _seed(repo, "copilot", BODIES["copilot"])
    await _seed(repo, "scan", BODIES["scan"])
    snapshot = await _load(repo, cloud="government")
    assert not snapshot.has("copilot") and snapshot.has("scan")
    assert snapshot.invalid == frozenset({"copilot"})


async def test_revision_of_follows_replaces() -> None:
    repo = InMemoryAdminConfigRepository(cloud="commercial")
    doc = await _seed(repo, "copilot", BODIES["copilot"])
    await repo.replace(
        CUSTOMER,
        SYSTEM_SETTING_KIND,
        doc.id.root,
        BODIES["copilot"],
        if_match=doc.etag.root,
        updated_by=ACTOR,
    )
    docs = await repo.list_by_kind(CUSTOMER, SYSTEM_SETTING_KIND)
    assert revision_of("copilot", docs) == 2
    assert revision_of("judge", docs) is None


def test_run_blocking_works_inside_and_outside_a_loop() -> None:
    async def load() -> StoredSettingsSnapshot:
        return StoredSettingsSnapshot.empty("loaded")

    assert run_blocking(load, limit_seconds=2).status == "loaded"

    async def inside() -> StoredSettingsSnapshot:
        return run_blocking(load, limit_seconds=2)

    assert asyncio.run(inside()).status == "loaded"


def test_run_blocking_bounds_a_hang_and_an_error() -> None:
    async def hang() -> StoredSettingsSnapshot:
        await asyncio.sleep(30)
        raise AssertionError

    async def boom() -> StoredSettingsSnapshot:
        raise RuntimeError("x")

    assert run_blocking(hang, limit_seconds=0.05).status == "unavailable"
    assert run_blocking(boom, limit_seconds=2).reason == STORED_SETTINGS_UNAVAILABLE


def test_cache_keeps_one_snapshot_per_key_but_not_unconfigured() -> None:
    cache = StoredSettingsCache()
    calls: list[str] = []

    def loader(status: Any) -> Any:
        def load() -> StoredSettingsSnapshot:
            calls.append(status)
            return StoredSettingsSnapshot.empty(status)

        return load

    first = cache.get_or_load("a", loader("loaded"))
    assert cache.get_or_load("a", loader("unavailable")) is first
    cache.get_or_load("b", loader("unconfigured"))
    cache.get_or_load("b", loader("unconfigured"))
    assert calls == ["loaded", "unconfigured", "unconfigured"]
    cache.clear()
    assert cache.get_or_load("a", loader("unavailable")).status == "unavailable"
