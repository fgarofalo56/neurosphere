"""GET /domains/{domain}/calibration-samples (PRP-16 round 2 item 14)."""

from __future__ import annotations

import asyncio

from neurosphere_core.evaluation.samples import CalibrationSample, build_calibration_sample
from quality_api_helpers import (  # pyright: ignore[reportMissingImports]
    ALICE,
    BOB,
    FINANCE,
    OPERATIONS,
    Api,
    T,
    make_api,
)

REF = "commercial:contoso:evaluation:dispute:" + "a" * 40
PATH = f"/domains/{FINANCE}/calibration-samples"


def _sample(
    ref: str = REF,
    *,
    domain: str = FINANCE,
    classification: str | None = "internal",
) -> CalibrationSample:
    return build_calibration_sample(
        subject_ref=ref,
        cloud="commercial",
        customer_id="contoso",
        domain_id=domain,
        dataset_id="ds-1",
        dataset_version="3",
        item_id="item-1",
        dimension="groundedness",
        classification=classification,
        judge_config_id="judge-a",
        judge_config_version="7",
        value=1.0,
        rubric_id="rubric-t",
        rubric_version="1",
        opened_at=T,
        payload={"question": "What is the limit?"},
    )


def _with(*samples: CalibrationSample, wire: bool = True) -> Api:
    api = make_api(wire=wire)
    for sample in samples:
        asyncio.run(api.store.put_calibration_sample(sample))
    return api


def test_returns_the_sample_for_a_viewer_in_scope() -> None:
    api = _with(_sample())
    response = api.get(ALICE, PATH, subject_ref=REF)
    assert response.status_code == 200
    body = response.json()
    assert body["subject_ref"] == REF
    assert body["item_id"] == "item-1"
    assert body["dimension"] == "groundedness"
    assert body["value"] == 1.0
    assert body["judge_config_id"] == "judge-a"
    assert body["judge_config_version"] == "7"
    assert body["rubric_version"] == "1"
    assert body["payload"] == {"question": "What is the limit?"}
    assert body["payload_withheld"] is False
    assert "customer_id" not in body


def test_restricted_sample_is_served_without_a_payload() -> None:
    api = _with(_sample(classification=None))
    body = api.get(ALICE, PATH, subject_ref=REF).json()
    assert body["payload"] is None
    assert body["payload_withheld"] is True
    assert body["withheld_reason"] == "restricted"


def test_unknown_subject_ref_is_404_problem_json() -> None:
    api = _with(_sample())
    response = api.get(ALICE, PATH, subject_ref="commercial:contoso:evaluation:dispute:nope")
    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/problem+json")


def test_out_of_scope_domain_is_403_and_leaks_nothing() -> None:
    api = _with(_sample(domain=OPERATIONS))
    response = api.get(ALICE, f"/domains/{OPERATIONS}/calibration-samples", subject_ref=REF)
    assert response.status_code == 403
    assert "What is the limit" not in response.text


def test_a_sample_in_another_domain_is_not_found_via_my_domain() -> None:
    api = _with(_sample(domain=OPERATIONS))
    assert api.get(ALICE, PATH, subject_ref=REF).status_code == 404
    assert (
        api.get(BOB, f"/domains/{OPERATIONS}/calibration-samples", subject_ref=REF).status_code
        == 200
    )


def test_missing_subject_ref_is_a_client_error() -> None:
    api = _with(_sample())
    assert api.get(ALICE, PATH).status_code in (400, 422)


def test_unauthenticated_is_401() -> None:
    api = _with(_sample())
    assert api.get(None, PATH, subject_ref=REF).status_code == 401


def test_absent_store_is_503() -> None:
    api = _with(wire=False)
    response = api.get(ALICE, PATH, subject_ref=REF)
    assert response.status_code == 503
    assert response.json()["reason"] == "evaluation_unconfigured"
