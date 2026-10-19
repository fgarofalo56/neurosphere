"""Wire contract: list/detail/review-request shapes, schema validity, unknown stays null."""

import json
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator

from neurosphere_api.recommendations.tests.support import (
    ALICE,
    CAROL,
    FINANCE,
    make_api,
    make_rec,
    rec_from_example,
)

SCHEMA_DIR = Path(__file__).resolve().parents[5] / "packages/contracts/schemas"
EXAMPLE_FILES = [
    "recommendation.cold-start-unused-agent.json",
    "recommendation.cost-spike-scored.json",
    "recommendation.model-right-sizing-estimate.json",
]


def validator() -> Draft202012Validator:
    # Schemas $ref siblings (common types); resolve them through a local registry.
    from referencing import Registry, Resource

    registry = Registry()
    for path in SCHEMA_DIR.rglob("*.schema.json"):
        doc = json.loads(path.read_text(encoding="utf-8"))
        registry = registry.with_resource(
            doc.get("$id", path.as_uri()), Resource.from_contents(doc)
        )
        registry = registry.with_resource(path.as_uri(), Resource.from_contents(doc))
    schema = json.loads(
        (SCHEMA_DIR / "recommendations/v1/recommendation.schema.json").read_text(encoding="utf-8")
    )
    return Draft202012Validator(schema, registry=registry)


def detail_path(rec_id: str) -> str:
    return f"/domains/{FINANCE}/items/{rec_id}"


def test_detail_matches_the_wire_contract() -> None:
    rec = make_rec(1)
    api = make_api(rec)
    response = api.get(ALICE, detail_path(rec.recommendation_id.root))
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"recommendation", "review", "execution"}
    assert body["review"] == {"state": "not_routed", "review_request_id": None}
    assert body["execution"] == {"executable": False, "reason": "action gates not passed"}
    assert body["recommendation"]["recommendation_id"] == rec.recommendation_id.root


@pytest.mark.parametrize("name", EXAMPLE_FILES)
def test_served_recommendation_is_schema_valid_and_round_trips(name: str) -> None:
    rec = rec_from_example(name)
    api = make_api(rec)
    body = api.get(ALICE, detail_path(rec.recommendation_id.root)).json()
    errors = list(validator().iter_errors(body["recommendation"]))
    assert errors == []
    listed = api.get(ALICE, f"/domains/{FINANCE}").json()
    assert list(validator().iter_errors(listed["items"][0])) == []
    assert listed["items"][0] == body["recommendation"]


def test_list_shape_filters_and_pagination() -> None:
    recs = [make_rec(n) for n in (1, 2, 3)]
    recs.append(make_rec(4, kind="unused_agent"))
    api = make_api(*recs)
    first = api.get(ALICE, f"/domains/{FINANCE}", limit=3).json()
    assert set(first) == {"items", "next_cursor"}
    assert len(first["items"]) == 3
    assert first["next_cursor"] is not None
    second = api.get(ALICE, f"/domains/{FINANCE}", limit=3, cursor=first["next_cursor"]).json()
    assert len(second["items"]) == 1
    assert second["next_cursor"] is None
    only = api.get(ALICE, f"/domains/{FINANCE}", kind="unused_agent").json()["items"]
    assert [i["kind"] for i in only] == ["unused_agent"]


@pytest.mark.parametrize(
    "params",
    [{"kind": "nonsense"}, {"limit": 0}, {"limit": 10_000}, {"q": "x" * 129}, {"cursor": "!!bad"}],
)
def test_bad_query_is_rejected(params: dict[str, Any]) -> None:
    api = make_api(make_rec(1))
    assert api.get(ALICE, f"/domains/{FINANCE}", **params).status_code == 422


def test_unknown_stays_null_never_zero() -> None:
    rec = rec_from_example("recommendation.cold-start-unused-agent.json")
    api = make_api(rec)
    body = api.get(ALICE, detail_path(rec.recommendation_id.root)).json()["recommendation"]
    assert body["coverage"]["observed_fraction"] is None
    assert body["owner"]["owner_id"] is None
    assert "score" not in body  # cold start: absent, never fabricated or 0
    assert list(validator().iter_errors(body)) == []


def test_unknown_item_is_404() -> None:
    api = make_api(make_rec(1))
    missing = "commercial:contoso:neurosphere:recommendation:rec-9999"
    assert api.get(ALICE, detail_path(missing)).status_code == 404


def test_review_request_flow_is_accepted_idempotent_and_reflected_in_detail() -> None:
    rec = make_rec(1)
    api = make_api(rec)
    rid = rec.recommendation_id.root
    first = api.post(CAROL, f"/domains/{FINANCE}/review-requests", {"recommendation_id": rid})
    assert first.status_code == 202
    created = first.json()
    assert set(created) == {"review_request_id", "state"}
    assert created["state"] == "pending_review"
    again = api.post(CAROL, f"/domains/{FINANCE}/review-requests", {"recommendation_id": rid})
    assert again.json() == created
    detail = api.get(ALICE, detail_path(rid)).json()
    assert detail["review"] == {
        "state": "pending_review",
        "review_request_id": created["review_request_id"],
    }


def test_review_request_for_unknown_recommendation_is_404() -> None:
    api = make_api(make_rec(1))
    body = {"recommendation_id": "commercial:contoso:neurosphere:recommendation:rec-9999"}
    assert api.post(CAROL, f"/domains/{FINANCE}/review-requests", body).status_code == 404


def test_review_request_requires_a_recommendation_id() -> None:
    api = make_api(make_rec(1))
    assert api.post(CAROL, f"/domains/{FINANCE}/review-requests", {}).status_code == 422
