"""PRP-137 item 5: repointing retires the old alias, the same target twice is unchanged."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest
from alias_harness import (  # pyright: ignore[reportMissingImports]
    FINANCE,
    STEWARD,
    VIEWER,
    AliasWorld,
    agent_id,
    body,
    build,
    configure_env,
)


@pytest.fixture(autouse=True)
def _auth(monkeypatch: pytest.MonkeyPatch) -> None:
    configure_env(monkeypatch)


def _operations(world: object) -> list[str]:
    docs = world.audit_docs()  # type: ignore[attr-defined]
    found: list[str] = []
    for doc in docs:
        text = json.dumps(doc, default=str)
        for op in ("agent_identity.alias_declare", "agent_identity.alias_retire"):
            if op in text:
                found.append(op)
    return found


def test_the_same_target_twice_is_unchanged() -> None:
    world = build()
    first = world.put(FINANCE, STEWARD, body()).json()
    second = world.put(FINANCE, STEWARD, body()).json()
    assert first["outcome"] == "created"
    assert second["outcome"] == "unchanged"
    assert second["alias_id"] is None and second["retired_alias_id"] is None
    assert second["reresolve_needed"] is False
    assert second["reresolve_job"] is None


def test_a_new_target_retires_the_old_alias_and_asks_for_reresolution() -> None:
    world = build()
    first = world.put(FINANCE, STEWARD, body(target=agent_id("fin-one"))).json()
    moved = world.put(FINANCE, STEWARD, body(target=agent_id("fin-two"))).json()
    assert moved["outcome"] == "repointed"
    assert moved["retired_alias_id"] == first["alias_id"]
    assert moved["alias_id"] not in (None, first["alias_id"])
    assert moved["reresolve_needed"] is True
    assert moved["reresolve_job"]["arguments"][-2:] == ["--external-agent-id", "asst-1"]
    read = world.get(FINANCE, VIEWER, source_id="foundry", external_agent_id="asst-1")
    assert read.json()["target_agent_id"] == agent_id("fin-two")


def test_a_repoint_is_audited_as_declare_and_retire() -> None:
    world = build()
    world.put(FINANCE, STEWARD, body(target=agent_id("fin-one")))
    assert _operations(world).count("agent_identity.alias_retire") == 0
    world.put(FINANCE, STEWARD, body(target=agent_id("fin-two")))
    ops = _operations(world)
    assert ops.count("agent_identity.alias_retire") == 1
    assert ops.count("agent_identity.alias_declare") >= 2


def test_an_unchanged_declaration_writes_no_retire_record() -> None:
    world = build()
    world.put(FINANCE, STEWARD, body())
    world.put(FINANCE, STEWARD, body())
    assert "agent_identity.alias_retire" not in _operations(world)


def _tick(world: AliasWorld, step: float) -> None:
    state = {"t": datetime(2026, 11, 22, 9, 0, 0, tzinfo=UTC)}

    def clock() -> datetime:
        state["t"] += timedelta(seconds=step)
        return state["t"]

    world.composed.app.state.catalog_clock = clock


def test_repointing_back_creates_a_third_alias() -> None:
    world = build()
    _tick(world, 5)
    ids = [
        world.put(FINANCE, STEWARD, body(target=agent_id(name))).json()
        for name in ("fin-one", "fin-two", "fin-one")
    ]
    assert [i["outcome"] for i in ids] == ["created", "repointed", "repointed"]
    assert len({i["alias_id"] for i in ids}) == 3


def test_repointing_back_within_one_second_is_refused() -> None:
    """Known limit of ``declare_agent_alias`` (item 1): alias ids hash the second, so going back
    to a retired target inside the same second reuses its id and the write is refused (409)."""
    world = build()
    _tick(world, 0)
    world.put(FINANCE, STEWARD, body(target=agent_id("fin-one")))
    world.put(FINANCE, STEWARD, body(target=agent_id("fin-two")))
    refused = world.put(FINANCE, STEWARD, body(target=agent_id("fin-one")))
    assert refused.status_code == 409
