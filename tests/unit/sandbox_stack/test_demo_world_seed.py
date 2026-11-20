"""PRP-71 item 3: the ``demo-world`` seed profile against in-memory stores and a fake hub.

Reuses the fakes of ``test_seed_stack.py`` (loaded by path under its own module name, so the two
files never shadow each other). No network: the curated entities and edges reach the catalog
repository, the telemetry-only agents do not, a second run creates nothing, the incident window is
rebased to be recent, and the loopback guard still refuses anything else.
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from neurosphere_core.catalog import EntityFilter
from neurosphere_core.paging.models import PageRequest

BASE = Path(__file__).resolve().parent / "test_seed_stack.py"
PROFILE = "demo-world"


def _load_base() -> ModuleType:
    spec = importlib.util.spec_from_file_location("sbx_seed_stack_fakes_for_demo_world", BASE)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


base = _load_base()
seed = base.seed


@pytest.fixture(autouse=True)
def _local_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NS_ENV", "local")
    for name in ("NS_CLOUD", "NS_AUTH_PSEUDONYM_KEY", "NS_AUTH_PSEUDONYM_KEY_REFERENCE"):
        monkeypatch.delenv(name, raising=False)


def _config() -> Any:
    return base._config(profile=PROFILE)  # pyright: ignore[reportPrivateUsage]


def _run(stack: Any, tmp_path: Path, at: datetime = base.RUN_TIME) -> dict[str, Any]:
    return base._run(stack, tmp_path, _config(), at)  # pyright: ignore[reportPrivateUsage]


def _entities(stack: Any) -> list[Any]:
    scope = asyncio.run(seed.worker_scope(stack.backends, _config()))
    found: list[Any] = []
    cursor: str | None = None
    while True:
        page = asyncio.run(
            stack.catalog.list_entities(
                scope, EntityFilter(), PageRequest(page_size=100, cursor=cursor)
            )
        )
        found += page.items
        cursor = page.next_cursor
        if cursor is None:
            return found


def _ndjson(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def _stamp(text: str) -> datetime:
    return datetime.fromisoformat(text).astimezone(UTC)


def test_every_curated_category_and_edge_reaches_the_repository(tmp_path: Path) -> None:
    stack = base.Stack()
    summary = _run(stack, tmp_path)
    scope = asyncio.run(seed.worker_scope(stack.backends, _config()))

    by_type: dict[str, int] = {}
    for entity in _entities(stack):
        kind = str(entity.entity_type)
        by_type[kind] = by_type.get(kind, 0) + 1
    assert by_type["agent"] == 32
    assert by_type["agent_version"] == 37
    assert by_type["tool"] == 16
    assert by_type["service"] == 7
    assert by_type["mcp_server"] == 1
    assert by_type["model_deployment"] == 4
    assert by_type["grounding_source"] == 15
    assert by_type["domain"] == 4
    assert by_type["owner"] == 10

    relations = _ndjson(tmp_path / "relations.ndjson")
    kinds = {r["relation_type"] for r in relations}
    assert {"owned_by", "reads", "writes", "depends_on", "delegates_to"} <= kinds
    for doc in relations:
        stable = seed.edge_id(
            doc["cloud"],
            doc["customer_id"],
            doc["relation_type"],
            doc["source_id"],
            doc["target_id"],
        )
        assert asyncio.run(stack.catalog.get_edge(scope, stable)) is not None, doc["id"]

    seeded = summary["seeded"]
    assert seeded["edges"] == len(relations)
    assert seeded["services"] == 7
    assert seeded["tools"] == 16
    assert seeded["mcp_server_entities"] == 1
    assert seeded["entities"] == sum(by_type.values())
    # agents keep their curated metadata (the entities went in before the telemetry)
    agents = [e for e in _entities(stack) if str(e.entity_type) == "agent"]
    assert all(a.tags and a.capabilities and a.environment for a in agents)
    # the worker, the five personas and the operator (admin plus the four other persona roles,
    # so one sign-in opens every role-gated page) hold grants over the demo world's domains
    assert seeded["grants"] == 11


def test_telemetry_only_agents_are_not_catalog_entities(tmp_path: Path) -> None:
    stack = base.Stack()
    _run(stack, tmp_path)
    manifest = json.loads((tmp_path / "run-manifest.json").read_text("utf-8"))
    undeclared = {a["agent_id"] for a in manifest["demo_world"]["undeclared_agents"]}
    assert len(undeclared) == 4
    assert undeclared.isdisjoint({str(e.id) for e in _entities(stack)})
    # ... but they do speak in the published telemetry, so the projection can discover them
    spoken = {
        d["canonical_agent_id"]
        for d in _ndjson(tmp_path / "telemetry.ndjson")
        if isinstance(d.get("canonical_agent_id"), str)
    }
    assert undeclared <= spoken
    relations = _ndjson(tmp_path / "relations.ndjson")
    assert not any(r["source_id"] in undeclared or r["target_id"] in undeclared for r in relations)


def test_second_run_creates_nothing_and_reports_skipped_existing(tmp_path: Path) -> None:
    stack = base.Stack()
    first = _run(stack, tmp_path / "one")
    count = len(_entities(stack))
    second = _run(stack, tmp_path / "two", at=base.RUN_TIME + timedelta(days=2, hours=3))

    assert second["skipped_existing"] > 0
    assert all(n == 0 for n in second["seeded"].values()), second["seeded"]
    assert len(_entities(stack)) == count
    # the shift was recovered from the ledger: the same incident window, nothing re-aged
    assert second["incident"] == first["incident"]


def test_the_incident_window_is_rebased_to_be_recent(tmp_path: Path) -> None:
    stack = base.Stack()
    summary = _run(stack, tmp_path)
    incident = summary["incident"]
    start, end = _stamp(incident["window"]["start"]), _stamp(incident["window"]["end"])

    assert end - start == timedelta(hours=1)
    age = base.RUN_TIME - end
    assert timedelta(minutes=30) <= age <= timedelta(minutes=35), age
    assert incident == json.loads((tmp_path / "incident-manifest.json").read_text("utf-8"))

    # the rebased data really contains the incident: failing spans inside the window, and nothing
    # in the future
    events = _ndjson(tmp_path / "telemetry.ndjson")
    times = [_stamp(e["event_time"]) for e in events]
    assert max(times) <= base.RUN_TIME
    inside = [e for e in events if start <= _stamp(e["event_time"]) < end]
    assert inside, "events fall inside the rebased incident window"
    assert any(e.get("outcome") in {"error", "timeout"} for e in inside)
    assert min(times) < start - timedelta(days=5), "the history precedes the incident"
    published = base._published_times(stack)  # pyright: ignore[reportPrivateUsage]
    assert max(published) <= base.RUN_TIME


def test_categories_include_services_and_the_standard_ones(tmp_path: Path) -> None:
    summary = _run(base.Stack(), tmp_path)
    assert set(summary["seeded"]) == set(seed.CATEGORIES) | set(seed.DEMO_CATEGORIES)
    assert summary["seeded"]["services"] > 0
    assert summary["seeded"]["ledger"] == base.FAKE_LANDED["ledger"]


def test_existing_profiles_keep_their_summary_shape(tmp_path: Path) -> None:
    summary = base._run(base.Stack(), tmp_path)  # pyright: ignore[reportPrivateUsage]
    assert set(summary) == {"seeded", "skipped_existing"}
    assert set(summary["seeded"]) == set(seed.CATEGORIES)


def test_the_loopback_guard_still_refuses_other_endpoints() -> None:
    env = base._env(NS_COSMOS_ENDPOINT="https://contoso.documents.azure.com:443/")  # pyright: ignore[reportPrivateUsage]
    with pytest.raises(seed.GuardError):
        seed.resolve_config(PROFILE, None, env)
    ok = seed.resolve_config(PROFILE, None, base._env())  # pyright: ignore[reportPrivateUsage]
    assert ok.cosmos_endpoint == "http://127.0.0.1:8081"


def test_the_hosted_seed_refuses_the_demo_world(capsys: pytest.CaptureFixture[str]) -> None:
    code = seed.main(["--profile", PROFILE, "--hosted", "registration.json"], env={})
    assert code == seed.EXIT_REFUSED
    assert "local and CI only" in capsys.readouterr().err


def test_demo_world_stores_the_feature_settings_once(tmp_path: Path) -> None:
    from neurosphere_core.admin import InMemoryAdminConfigRepository
    from neurosphere_core.admin.runtime import SYSTEM_SETTING_KIND
    from neurosphere_core.audit import AuditRepository
    from neurosphere_core.audit.store import InMemoryAuditStore

    stack = base.Stack()
    repository = InMemoryAdminConfigRepository(cloud="commercial")
    stack.backends.admin_config = repository
    stack.backends.audit = AuditRepository(InMemoryAuditStore())

    first = _run(stack, tmp_path / "one")
    assert first["seeded"]["settings"] == 6
    stored = asyncio.run(repository.list_by_kind("synthco", SYSTEM_SETTING_KIND))
    assert len(stored) == 6

    second = _run(stack, tmp_path / "two")
    assert second["seeded"]["settings"] == 0
    assert second["skipped_existing"] >= 6
    assert len(asyncio.run(repository.list_by_kind("synthco", SYSTEM_SETTING_KIND))) == 6
