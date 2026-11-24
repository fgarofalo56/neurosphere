"""Node facets (PRP-74 item 1, criteria 2 and 3)."""

import json

from map_api_helpers import (  # pyright: ignore[reportMissingImports]
    ALICE,
    FINANCE,
    agent_doc,
    agent_id,
    example,
    make_api,
    model_doc,
    person_doc,
    put_points,
    service_doc,
    service_id,
    subject_point,
)
from neurosphere_api.map.facets import cluster_facets, facets_of
from neurosphere_contracts.catalog.v1.service import Service

FACET_KEYS = {
    "entity_type",
    "environment",
    "cloud",
    "tags",
    "lifecycle_status",
    "discovery",
    "health",
    "error_rate",
    "error_count",
    "request_count",
    "last_error_at",
    "sensitivity_categories",
    "residency_geography",
}


def _by_id(body: dict) -> dict[str, dict]:
    return {n["id"]: n for n in body["nodes"]}


def test_every_node_carries_the_facet_set_and_unknown_is_not_zero() -> None:
    api = make_api()
    api.seed(agent_doc("alpha"), service_doc("orders"))
    nodes = _by_id(api.get(ALICE, FINANCE).json())
    for node in nodes.values():
        assert FACET_KEYS <= set(node["facets"])
    facets = nodes[agent_id("alpha")]["facets"]
    assert facets["entity_type"] == "agent"
    assert facets["cloud"] == "commercial"
    assert facets["health"] == "unknown"
    assert facets["error_rate"] is None
    assert facets["error_count"] is None
    assert facets["request_count"] is None
    assert facets["last_error_at"] is None


def test_agent_error_fields_equal_the_subject_point() -> None:
    api = make_api()
    api.seed(agent_doc("alpha"))
    put_points(
        api,
        subject_point(f"agent:{agent_id('alpha')}", events=40, error_count=10, error_rate=0.25),
    )
    node = _by_id(api.get(ALICE, FINANCE).json())[agent_id("alpha")]
    assert node["facets"]["error_rate"] == 0.25
    assert node["facets"]["error_count"] == 10
    assert node["facets"]["request_count"] == 40
    assert node["facets"]["health"] == "failing"
    assert node["metrics"]["health"] == "failing"
    assert node["health_inferred"] is False


def test_a_measured_zero_is_zero_not_unknown() -> None:
    api = make_api()
    api.seed(agent_doc("alpha"))
    put_points(api, subject_point(f"agent:{agent_id('alpha')}", error_count=0, error_rate=0.0))
    facets = _by_id(api.get(ALICE, FINANCE).json())[agent_id("alpha")]["facets"]
    assert facets["error_rate"] == 0.0
    assert facets["error_count"] == 0
    assert facets["health"] == "ok"


def test_model_node_shows_model_level_values_for_every_deployment() -> None:
    api = make_api()
    api.seed(model_doc("dep-1"), model_doc("dep-2"))
    put_points(
        api,
        subject_point("model:azure_openai/gpt-4o", events=9, error_count=3, error_rate=0.3),
    )
    nodes = _by_id(api.get(ALICE, FINANCE).json())
    for node in nodes.values():
        assert node["facets"]["entity_type"] == "model_deployment"
        assert node["facets"]["error_count"] == 3
        assert node["facets"]["health"] == "failing"


def test_entity_fields_flow_into_the_facets() -> None:
    api = make_api()
    raw = example("grounding_source.sensitivity-residency.json")
    raw["domain_id"] = FINANCE
    api.seed(raw)
    node = _by_id(api.get(ALICE, FINANCE).json())[raw["id"]]
    facets = node["facets"]
    assert facets["environment"] == "production"
    assert facets["tags"] == ["claims"]
    assert facets["sensitivity_categories"] == ["pii", "phi"]
    assert facets["residency_geography"] == "eu_eea"
    assert facets["lifecycle_status"] == "active"


def test_cluster_node_has_a_null_entity_type() -> None:
    api = make_api()
    api.seed(agent_doc("a1"), agent_doc("a2"), service_doc("orders"))
    api.limits(max_nodes=1)
    body = api.get(ALICE, FINANCE).json()
    clusters = [n for n in body["nodes"] if n["kind"] == "cluster"]
    assert clusters
    for cluster in clusters:
        assert cluster["facets"]["entity_type"] is None
        assert cluster["facets"]["health"] == "unknown"
    assert cluster_facets().entity_type is None


def test_person_facets_and_label_hold_no_real_name() -> None:
    api = make_api()
    real_name = "zebulonquixote0001"  # the catalog person id carries it; the wire must not
    api.seed(person_doc(real_name), agent_doc("alpha"))
    body = api.get(ALICE, FINANCE).json()
    person = next(n for n in body["nodes"] if n["kind"] == "person")
    assert person["facets"]["entity_type"] == "person"
    assert person["label"] == person["id"]
    assert real_name not in json.dumps(body).lower()


def test_facets_of_without_a_point_and_with_a_derived_health() -> None:
    entity = Service.model_validate(example("service.minimal-and-typical.json"))
    plain = facets_of(entity, None)
    assert plain.health == "unknown"
    assert plain.error_rate is None
    assert plain.environment is not None
    assert facets_of(entity, None, derived_health="degraded").health == "degraded"
    point = subject_point(f"service:{service_id('x')}", error_rate=0.0, error_count=0)
    # a measured point wins over any derived value
    assert facets_of(entity, point, derived_health="failing").health == "ok"
