"""Deltas are filtered by the session's CURRENT scope at send time, never by the scope at
subscribe time; client-supplied domains and customers are requests, not scope.
"""

from authz.authz_helpers import (  # pyright: ignore[reportMissingImports]
    ALICE,
    BOB,
    FINANCE,
    GOV_FINANCE,
    HR,
    OPERATIONS,
    OTHER_CUSTOMER_FINANCE,
    policy,
    role,
)
from neurosphere_core.auth.scope import Role

from .rt_helpers import build_rig, seed_domain, until_pong

POLICIES = (
    policy(ALICE, role(Role.VIEWER, FINANCE, OPERATIONS)),
    policy(BOB, role(Role.VIEWER, FINANCE)),
)


def test_subscribe_to_a_permitted_domain_gets_a_delta_with_coverage_and_seq() -> None:
    rig = build_rig(*POLICIES)
    seed_domain(rig.aggregates, FINANCE, p95_ms=120, requests=40, errors=1)
    with rig.client() as client, rig.connect(client, BOB) as ws:
        ws.send_json({"type": "subscribe", "domain_id": FINANCE})
        assert ws.receive_json() == {"type": "subscribed", "domain_id": FINANCE}
        delta = ws.receive_json()
    assert delta["type"] == "delta"
    assert delta["domain_id"] == FINANCE
    assert delta["seq"] == 1
    assert delta["emitted_at"].endswith("Z")
    assert delta["edges"] == []
    assert delta["coverage"]["state"] == "complete"
    assert delta["coverage"]["lag_seconds"] == 1.0
    assert delta["coverage"]["as_of"] is not None
    node = delta["nodes"][0]
    assert node["id"] == FINANCE
    assert node["metrics"]["latency_p95_ms"] == 120
    assert node["metrics"]["frequency"] == 40
    assert node["metrics"]["health"] == "ok"
    assert node["metrics"]["tokens"] is None  # not aggregated at this grain: null, never 0


def test_unknown_metrics_stay_null_and_the_gap_is_labelled() -> None:
    rig = build_rig(*POLICIES)  # nothing seeded, no aggregate status
    with rig.client() as client, rig.connect(client, BOB) as ws:
        ws.send_json({"type": "subscribe", "domain_id": FINANCE})
        ws.receive_json()
        delta = ws.receive_json()
    metrics = delta["nodes"][0]["metrics"]
    assert metrics["latency_p95_ms"] is None
    assert metrics["frequency"] is None
    assert metrics["health"] == "unknown"
    assert delta["coverage"] == {"state": "unknown", "lag_seconds": None, "as_of": None}


def test_a_stale_watermark_is_labelled_delayed() -> None:
    rig = build_rig(*POLICIES)
    seed_domain(rig.aggregates, FINANCE, lag_seconds=300.0)
    with rig.client() as client, rig.connect(client, BOB) as ws:
        ws.send_json({"type": "subscribe", "domain_id": FINANCE})
        ws.receive_json()
        delta = ws.receive_json()
    assert delta["coverage"]["state"] == "delayed"
    assert delta["coverage"]["lag_seconds"] == 300.0


def test_subscribing_without_data_read_is_refused_and_pushes_nothing() -> None:
    rig = build_rig(*POLICIES)
    for domain in (HR, OPERATIONS, OTHER_CUSTOMER_FINANCE, GOV_FINANCE):
        seed_domain(rig.aggregates, domain)
    with rig.client() as client, rig.connect(client, BOB) as ws:
        for domain in (HR, OPERATIONS, OTHER_CUSTOMER_FINANCE, GOV_FINANCE):
            ws.send_json({"type": "subscribe", "domain_id": domain})
            reply = ws.receive_json()
            assert reply["type"] == "error"
            assert reply["code"] == "forbidden"
            assert reply["domain_id"] == domain
        rig.tick(client, 2)
        assert until_pong(ws) == []  # still open, nothing was pushed


def test_client_supplied_customer_or_scope_fields_are_rejected_not_trusted() -> None:
    rig = build_rig(*POLICIES)
    seed_domain(rig.aggregates, FINANCE)
    with rig.client() as client, rig.connect(client, BOB) as ws:
        ws.send_json({"type": "subscribe", "domain_id": FINANCE, "customer_id": "fabrikam"})
        reply = ws.receive_json()
        assert reply["type"] == "error"
        assert reply["code"] == "invalid_schema"
        ws.send_json({"type": "subscribe", "domain_id": FINANCE, "allowed_domains": [HR]})
        assert ws.receive_json()["code"] == "invalid_schema"
        ws.send_text("not json")
        assert ws.receive_json()["code"] == "invalid_schema"


def test_permissions_narrowed_mid_session_stop_deltas_for_the_dropped_domain() -> None:
    rig = build_rig(*POLICIES)
    seed_domain(rig.aggregates, FINANCE, p95_ms=100)
    seed_domain(rig.aggregates, OPERATIONS, p95_ms=100)
    with rig.client() as client, rig.connect(client, ALICE) as ws:
        for domain in (FINANCE, OPERATIONS):
            ws.send_json({"type": "subscribe", "domain_id": domain})
            assert ws.receive_json()["type"] == "subscribed"
            assert ws.receive_json()["domain_id"] == domain  # first delta
        rig.tick(client)
        assert until_pong(ws) == []  # nothing changed: nothing pushed

        # Narrow Alice to Finance only, and change Operations data so that an unfiltered
        # gateway WOULD push a delta for it on the next tick.
        rig.h.repo.put_principal(policy(ALICE, role(Role.VIEWER, FINANCE)))
        rig.h.deriver.invalidate_all()
        seed_domain(rig.aggregates, OPERATIONS, p95_ms=999)
        seed_domain(rig.aggregates, FINANCE, p95_ms=101)
        rig.tick(client)
        messages = until_pong(ws)

        deltas = [m for m in messages if m["type"] == "delta"]
        assert [d["domain_id"] for d in deltas] == [FINANCE]
        assert deltas[0]["nodes"][0]["metrics"]["latency_p95_ms"] == 101
        denied = [m for m in messages if m["type"] == "error"]
        assert denied == [
            {
                "type": "error",
                "code": "forbidden",
                "reason": "scope_narrowed",
                "domain_id": OPERATIONS,
            }
        ]

        # Subsequent ticks never push Operations again, even though its data keeps changing.
        seed_domain(rig.aggregates, OPERATIONS, p95_ms=1000)
        rig.tick(client, 2)
        assert all(m.get("domain_id") != OPERATIONS for m in until_pong(ws))
        # And re-subscribing is refused.
        ws.send_json({"type": "subscribe", "domain_id": OPERATIONS})
        assert ws.receive_json()["code"] == "forbidden"
    assert rig.registry.counters.scope_denied_deltas == 1


def test_unchanged_data_is_not_resent_until_the_heartbeat() -> None:
    rig = build_rig(*POLICIES, heartbeat_seconds=6)
    seed_domain(rig.aggregates, FINANCE)
    with rig.client() as client, rig.connect(client, BOB) as ws:
        ws.send_json({"type": "subscribe", "domain_id": FINANCE})
        ws.receive_json()
        assert ws.receive_json()["seq"] == 1
        rig.tick(client)  # +2 s
        assert until_pong(ws) == []
        rig.tick(client, 2)  # +6 s since the last delta: heartbeat
        beat = until_pong(ws)
        assert [m["seq"] for m in beat] == [2]  # seq is monotonic
        assert beat[0]["coverage"]["lag_seconds"] > 1.0  # lag keeps growing, labelled honestly
