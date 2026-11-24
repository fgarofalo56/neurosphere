"""Topology push (PRP-74 item 4): a ``topology`` message follows a catalog write within one poll
interval, an unchanged graph sends none, and the send-time scope check and revocation behave as
for deltas. ``NS_MAP_TOPOLOGY_ENABLED=false`` sends nothing and builds no source.
"""

import asyncio
import sys
from pathlib import Path
from typing import Any

import pytest
from authz.authz_helpers import (  # pyright: ignore[reportMissingImports]
    ALICE,
    BOB,
    FINANCE,
    OPERATIONS,
    policy,
    role,
)
from neurosphere_core.auth.scope import Role
from neurosphere_core.catalog.repo import InMemoryCatalogRepository

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "map_topology_api"))

import topology_helpers as th  # pyright: ignore[reportMissingImports]

from .rt_helpers import Rig, build_rig, drain, revoke, seed_domain, until_pong

POLICIES = (
    policy(ALICE, role(Role.VIEWER, FINANCE, OPERATIONS)),
    policy(BOB, role(Role.VIEWER, FINANCE)),
    policy(th.STEWARD, role(Role.DOMAIN_STEWARD, FINANCE, OPERATIONS)),
)


@pytest.fixture(autouse=True)
def _fast_topology_poll(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NS_MAP_TOPOLOGY_POLL_SECONDS", "1")


def _rig(**settings: Any) -> tuple[Rig, InMemoryCatalogRepository]:
    rig = build_rig(*POLICIES, **settings)
    repo = InMemoryCatalogRepository()
    rig.h.app.state.catalog_repository = repo
    seed_domain(rig.aggregates, FINANCE)
    seed_domain(rig.aggregates, OPERATIONS)
    return rig, repo


def _write(rig: Rig, repo: InMemoryCatalogRepository, *docs: dict[str, Any]) -> None:
    async def run() -> None:
        await th.seed(repo, await th.scope_of(rig.h, th.STEWARD), *docs)

    asyncio.run(run())


def _subscribe(ws: Any, domain: str) -> None:
    ws.send_json({"type": "subscribe", "domain_id": domain})
    assert ws.receive_json()["type"] == "subscribed"
    assert ws.receive_json()["type"] == "delta"


def _topology(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [m for m in messages if m["type"] == "topology"]


def test_a_catalog_write_is_pushed_as_a_topology_message_within_one_poll() -> None:
    rig, repo = _rig()
    _write(rig, repo, th.agent_doc("a1"))
    with rig.client() as client, rig.connect(client, BOB) as ws:
        _subscribe(ws, FINANCE)
        rig.tick(client)
        assert _topology(until_pong(ws)) == []  # the baseline is not a change

        sent_before = rig.registry.counters.deltas_sent
        _write(rig, repo, th.agent_doc("a2"))
        rig.tick(client)
        found = _topology(until_pong(ws))
    assert len(found) == 1
    message = found[0]
    assert message["domain_id"] == FINANCE
    assert message["change_kinds"] == ["node_added"]
    assert message["entity_ids"] == [th.agent_id("a2")]
    assert message["refetch"] is True
    assert message["truncated"] is False
    assert message["changed_at"].endswith("Z")
    assert message["emitted_at"].endswith("Z")
    assert isinstance(message["seq"], int)
    assert rig.registry.counters.deltas_sent == sent_before + 1
    assert rig.h.app.state.map_topology is not None  # built lazily, cached on app.state


def test_an_unchanged_graph_sends_no_topology_message() -> None:
    rig, repo = _rig(heartbeat_seconds=6)
    _write(rig, repo, th.agent_doc("a1"))
    with rig.client() as client, rig.connect(client, BOB) as ws:
        _subscribe(ws, FINANCE)
        for _ in range(5):
            rig.tick(client)
        messages = until_pong(ws)
    assert _topology(messages) == []
    assert {m["type"] for m in messages} <= {"delta"}  # only the heartbeat


def test_scope_narrowing_drops_the_topology_message_with_scope_narrowed() -> None:
    rig, repo = _rig()
    with rig.client() as client, rig.connect(client, ALICE) as ws:
        _subscribe(ws, FINANCE)
        _subscribe(ws, OPERATIONS)
        rig.tick(client)
        assert until_pong(ws) == []

        rig.h.repo.put_principal(policy(ALICE, role(Role.VIEWER, FINANCE)))
        rig.h.deriver.invalidate_all()
        _write(rig, repo, th.agent_doc("secret", OPERATIONS), th.agent_doc("open", FINANCE))
        rig.tick(client)
        messages = until_pong(ws)
        rig.tick(client, 2)
        later = until_pong(ws)
    topology = _topology(messages)
    assert [m["domain_id"] for m in topology] == [FINANCE]
    assert th.agent_id("secret") not in str(messages)
    assert [m["reason"] for m in messages if m["type"] == "error"] == ["scope_narrowed"]
    assert all(m.get("domain_id") != OPERATIONS for m in later)
    assert rig.registry.counters.scope_denied_deltas == 1


def test_revocation_closes_a_session_with_a_pending_topology_change() -> None:
    rig, repo = _rig()
    with rig.client() as client, rig.connect(client, BOB) as ws:
        _subscribe(ws, FINANCE)
        _write(rig, repo, th.agent_doc("a1"))
        revoke(rig, BOB, at_offset=1.0)
        rig.tick_until_closed(client)
        _, code = drain(ws)
    assert code == 4403


def test_switch_off_sends_nothing_and_builds_no_source(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NS_MAP_TOPOLOGY_ENABLED", "false")
    rig, repo = _rig()
    with rig.client() as client, rig.connect(client, BOB) as ws:
        _subscribe(ws, FINANCE)
        _write(rig, repo, th.agent_doc("a1"))
        rig.tick(client, 3)
        assert _topology(until_pong(ws)) == []
    assert getattr(rig.h.app.state, "map_topology", None) is None


def test_without_a_catalog_repository_the_gateway_still_serves_deltas() -> None:
    rig = build_rig(*POLICIES)
    seed_domain(rig.aggregates, FINANCE)
    with rig.client() as client, rig.connect(client, BOB) as ws:
        _subscribe(ws, FINANCE)
        rig.tick(client, 2)
        assert _topology(until_pong(ws)) == []
