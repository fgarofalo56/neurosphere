"""Assertions shared by the in-memory and the Cosmos-backed wiring tests."""

from __future__ import annotations

import map_api_helpers as map_helpers  # pyright: ignore[reportMissingImports]
from fastapi.testclient import TestClient

from .support import (
    ALICE,
    BOB,
    FINANCE,
    OPERATIONS,
    P95_MS,
    VIEWPORT,
    Wiring,
    drain,
    next_of_type,
    until_pong,
)


def check_viewport(w: Wiring, client: TestClient) -> None:
    """Permitted domain: 200 with the seeded agent and a coverage label; another: 403; none: 401."""
    ok = client.get(VIEWPORT.format(domain=FINANCE), headers=w.h.auth(ALICE))
    assert ok.status_code == 200, ok.text
    body = ok.json()
    assert body["domain_id"] == FINANCE
    assert map_helpers.agent_id("wired") in {n["id"] for n in body["nodes"]}
    assert body["coverage"]["state"] in {"complete", "partial", "delayed", "unknown"}
    assert body["coverage"]["as_of"] is not None, "the aggregate watermark must be read"
    other = client.get(VIEWPORT.format(domain=FINANCE), headers=w.h.auth(BOB))
    assert other.status_code == 403, other.text
    assert "wired" not in other.text
    assert client.get(VIEWPORT.format(domain=FINANCE)).status_code == 401


def check_delta_and_scope(w: Wiring, client: TestClient) -> None:
    """A subscription to a permitted domain gets a delta; another domain's never arrives."""
    with w.connect(client, ALICE) as ws:
        ws.send_json({"type": "subscribe", "domain_id": FINANCE})
        delta = next_of_type(ws, "delta")
        assert delta["domain_id"] == FINANCE
        assert delta["nodes"][0]["id"] == FINANCE
        assert delta["nodes"][0]["metrics"]["latency_p95_ms"] == P95_MS
        ws.send_json({"type": "subscribe", "domain_id": OPERATIONS})  # aggregates exist, scope no
        ws.send_json({"type": "totally-unknown-type"})
        later = until_pong(ws)
        assert not [m for m in later if m.get("type") == "delta" and m["domain_id"] == OPERATIONS]


def check_revocation_closes_socket(w: Wiring, client: TestClient) -> None:
    """RevocationService.revoke fans out to the gateway registry: 4403 at once, others untouched."""
    assert client.portal is not None
    with w.connect(client, ALICE) as alice, w.connect(client, BOB) as bob:
        alice.send_json({"type": "subscribe", "domain_id": FINANCE})
        next_of_type(alice, "delta")
        bob.send_json({"type": "subscribe", "domain_id": OPERATIONS})
        next_of_type(bob, "delta")
        assert w.registry.session_count == 2

        outcome = client.portal.call(w.revoke, ALICE)

        assert outcome.fanout.sessions_closed >= 1
        _, code = drain(alice)
        assert code == 4403
        assert not [m for m in until_pong(bob) if m.get("type") == "error"]  # Bob is untouched
    assert w.auditor.events[0].phase == "intent"
