"""Viewport scope, pseudonyms, coverage and null metrics (PRP-18 item 2)."""

from datetime import timedelta

from map_api_helpers import (  # pyright: ignore[reportMissingImports]
    ALICE,
    BOB,
    FINANCE,
    NOW,
    OPERATIONS,
    agent_doc,
    agent_id,
    make_api,
    make_edge,
    model_doc,
    person_doc,
)


def test_other_domain_is_forbidden_and_unauthenticated_is_rejected() -> None:
    api = make_api()
    api.seed(agent_doc("fin", FINANCE), agent_doc("ops", OPERATIONS))
    assert api.get(ALICE, OPERATIONS).status_code == 403
    assert api.get(BOB, FINANCE).status_code == 403
    assert api.get(None, FINANCE).status_code == 401


def test_client_supplied_scope_values_do_not_widen_the_view() -> None:
    api = make_api()
    api.seed(agent_doc("fin", FINANCE), agent_doc("ops", OPERATIONS))
    body = api.get(
        ALICE, FINANCE, customer_id="fabrikam", domain_id=OPERATIONS, domain_ids=OPERATIONS
    ).json()
    assert [n["id"] for n in body["nodes"]] == [agent_id("fin")]


def test_out_of_scope_nodes_and_intermediates_never_appear() -> None:
    api = make_api()
    api.seed(
        agent_doc("fin-a", FINANCE),
        agent_doc("fin-b", FINANCE),
        agent_doc("ops-x", OPERATIONS),
    )
    api.seed_edges(
        make_edge("direct", agent_id("fin-a"), agent_id("fin-b"), FINANCE),
        make_edge("to-ops", agent_id("fin-a"), agent_id("ops-x"), FINANCE),
        make_edge("from-ops", agent_id("ops-x"), agent_id("fin-b"), OPERATIONS),
    )
    response = api.get(ALICE, FINANCE)
    body = response.json()
    ids = {n["id"] for n in body["nodes"]}
    assert ids == {agent_id("fin-a"), agent_id("fin-b")}
    assert agent_id("ops-x") not in response.text
    # Only the direct edge survives: nothing bridges through the out-of-scope intermediate.
    assert [e["source"] + ">" + e["target"] for e in body["edges"]] == [
        agent_id("fin-a") + ">" + agent_id("fin-b")
    ]
    for edge in body["edges"]:
        assert edge["source"] in ids
        assert edge["target"] in ids


def test_edges_to_nodes_outside_a_cluster_page_are_dropped_not_dangling() -> None:
    api = make_api()
    api.seed(*(agent_doc(f"a{i}") for i in range(6)))
    api.seed_edges(
        *(make_edge(f"e{i}", agent_id(f"a{i}"), agent_id(f"a{i + 1}")) for i in range(5))
    )
    api.limits(max_nodes=3)
    page = api.get(ALICE, FINANCE, cluster_id="kind:agent", node_budget=3).json()
    ids = {n["id"] for n in page["nodes"]}
    assert len(ids) == 3
    assert page["edges"]
    assert all(e["source"] in ids and e["target"] in ids for e in page["edges"])


def test_people_are_pseudonymized_by_default() -> None:
    api = make_api()
    api.seed(person_doc("0123456789abcdef"), agent_doc("fin"))
    response = api.get(ALICE, FINANCE)
    body = response.json()
    person = next(n for n in body["nodes"] if n["kind"] == "person")
    assert person["label"].startswith("p-")
    assert person["id"] == person["label"]
    assert "0123456789abcdef" not in response.text
    assert ":entra:person:" not in response.text


def test_pseudonym_is_stable_and_not_the_catalog_id() -> None:
    api = make_api()
    api.seed(person_doc("0123456789abcdef"))
    first = api.get(ALICE, FINANCE).json()["nodes"][0]["id"]
    second = api.get(ALICE, FINANCE).json()["nodes"][0]["id"]
    assert first == second
    assert first != "commercial:contoso:entra:person:psn_0123456789abcdef"


def test_unknown_metrics_are_null_never_zero() -> None:
    api = make_api()
    api.seed(agent_doc("fin"), model_doc("gpt-4o-prod"))
    body = api.get(ALICE, FINANCE).json()
    for node in body["nodes"]:
        metrics = node["metrics"]
        assert metrics["tokens"] is None
        assert metrics["frequency"] is None
        assert metrics["latency_p95_ms"] is None
        assert metrics["health"] == "unknown"
    model = next(n for n in body["nodes"] if n["kind"] == "model")
    assert model["metrics"]["context_size"] != 0


def test_edges_carry_provenance() -> None:
    api = make_api()
    api.seed(agent_doc("a"), agent_doc("b"), agent_doc("c"), agent_doc("d"))
    api.seed_edges(
        make_edge("inf", agent_id("a"), agent_id("b"), status_file="inferred"),
        make_edge("decl", agent_id("b"), agent_id("c"), status_file="asserted"),
        make_edge(
            "obs",
            agent_id("c"),
            agent_id("d"),
            status_file="asserted",
            evidence_ids=["trace:abc123"],
        ),
    )
    edges = {e["id"].rsplit(":", 1)[-1]: e for e in api.get(ALICE, FINANCE).json()["edges"]}
    assert edges["inf"]["provenance"] == "inferred"
    assert edges["decl"]["provenance"] == "declared"
    assert edges["obs"]["provenance"] == "observed"
    assert edges["obs"]["last_observed_at"]


def test_coverage_states_from_aggregate_status() -> None:
    api = make_api()
    api.seed(agent_doc("fin"))
    fresh = api.get(ALICE, FINANCE).json()["coverage"]
    assert fresh["state"] == "complete"
    assert fresh["lag_seconds"] == 0.0
    assert fresh["as_of"]

    api.set_watermark(NOW - timedelta(minutes=5))
    late = api.get(ALICE, FINANCE).json()["coverage"]
    assert late["state"] == "delayed"
    assert late["lag_seconds"] == 300.0

    api.set_watermark(None)
    unknown = api.get(ALICE, FINANCE).json()["coverage"]
    assert unknown == {"state": "unknown", "lag_seconds": None, "as_of": None}


def test_missing_collaborators_fail_closed_with_503() -> None:
    api = make_api()
    api.seed(agent_doc("fin"))
    del api.h.app.state.aggregate_reader
    assert api.get(ALICE, FINANCE).status_code == 503
    api.h.app.state.aggregate_reader = api.store
    del api.h.app.state.map_pseudonymizer
    assert api.get(ALICE, FINANCE).status_code == 503
