"""Evaluation quality API: scope isolation, null-not-zero, calibration state, pilot rate."""

from __future__ import annotations

import pytest
from neurosphere_api.evaluation import compute_quality, pilot_grounded_rate
from neurosphere_core.evaluation.calibration import DriftAlert, proportion_interval
from neurosphere_core.evaluation.store import SamplingCoverage
from quality_api_helpers import (  # pyright: ignore[reportMissingImports]
    ALICE,
    BOB,
    FINANCE,
    JUDGE_CONFIG,
    OPERATIONS,
    T,
    make_api,
    make_report,
    make_result,
    score,
)

OPS_SUBJECT = "commercial:contoso:foundry:agent_version:ops-secret-bot/v=1"
TARGET_LABEL = "pilot-set target: at least 90%"
PROGRAMMATIC = {"judge_kind": "programmatic", "program_version": "1"}


def seeded():
    fin = make_result(1)
    ops = make_result(2, domain=OPERATIONS, subject_id=OPS_SUBJECT)
    other_customer = make_result(
        3,
        customer_id="fabrikam",
        domain_id="commercial:fabrikam:catalog:domain:finance",
        subject_id="commercial:fabrikam:foundry:agent_version:x/v=1",
    )
    other_cloud = make_result(
        4,
        cloud="government",
        domain_id="government:contoso:catalog:domain:finance",
        subject_id="government:contoso:foundry:agent_version:x/v=1",
        data_handling={"data_state": "redacted", "boundary_cloud": "government"},
    )
    return make_api(fin, ops, other_customer, other_cloud), fin, ops


# --- isolation -----------------------------------------------------------------------------


@pytest.mark.parametrize("route", ["results", "quality"])
def test_out_of_scope_domain_is_403_problem_json(route: str) -> None:
    api, _, _ = seeded()
    response = api.get(ALICE, f"/domains/{OPERATIONS}/{route}")
    assert response.status_code == 403
    assert response.headers["content-type"].startswith("application/problem+json")
    assert "ops-secret-bot" not in response.text


def test_results_never_include_other_domain_customer_or_cloud() -> None:
    api, fin, _ = seeded()
    body = api.get(ALICE, f"/domains/{FINANCE}/results").json()
    assert [i["evaluation_id"] for i in body["items"]] == [fin.evaluation_id.root]
    assert body["next_cursor"] is None
    assert "ops-secret-bot" not in str(body) and "fabrikam" not in str(body)
    assert "government" not in str(body)


def test_quality_never_includes_other_scopes_data() -> None:
    api, _, _ = seeded()
    fin_only = api.get(ALICE, f"/domains/{FINANCE}/quality").json()
    sizes = [p["sample_size"] for t in fin_only["trends"] for p in t["points"]]
    # Only the one finance result (groundedness 400, safety 0) contributes.
    assert sorted(sizes) == [0, 400]
    assert "ops-secret-bot" not in str(fin_only)


def test_each_viewer_sees_only_their_domain() -> None:
    api, fin, ops = seeded()
    a = api.get(ALICE, f"/domains/{FINANCE}/results").json()["items"]
    b = api.get(BOB, f"/domains/{OPERATIONS}/results").json()["items"]
    assert [i["evaluation_id"] for i in a] == [fin.evaluation_id.root]
    assert [i["evaluation_id"] for i in b] == [ops.evaluation_id.root]


@pytest.mark.parametrize("route", ["results", "quality"])
def test_caller_supplied_scope_params_never_widen_scope(route: str) -> None:
    api, _, _ = seeded()
    params = {"domain_id": OPERATIONS, "customer_id": "fabrikam"}
    assert api.get(ALICE, f"/domains/{FINANCE}/{route}", **params).status_code == 200
    assert api.get(ALICE, f"/domains/{OPERATIONS}/{route}", **params).status_code == 403
    body = api.get(ALICE, f"/domains/{FINANCE}/results", **params).json()
    assert [i["evaluation_id"] for i in body["items"]] == ["eval:r-0001"]


@pytest.mark.parametrize("route", ["results", "quality"])
def test_unauthenticated_is_401_and_unknown_domain_403(route: str) -> None:
    api, _, _ = seeded()
    assert api.get(None, f"/domains/{FINANCE}/{route}").status_code == 401
    ghost = "commercial:contoso:catalog:domain:ghost"
    assert api.get(ALICE, f"/domains/{ghost}/{route}").status_code == 403


@pytest.mark.parametrize("route", ["results", "quality"])
def test_policy_store_outage_is_503(route: str) -> None:
    api, _, _ = seeded()
    api.h.repo.fail_with(ConnectionError("policy store down"))
    response = api.get(ALICE, f"/domains/{FINANCE}/{route}")
    assert response.status_code == 503
    assert response.json()["code"] == "dependency_transient"


@pytest.mark.parametrize("route", ["results", "quality"])
def test_absent_store_is_503(route: str) -> None:
    api = make_api(make_result(1), wire=False)
    response = api.get(ALICE, f"/domains/{FINANCE}/{route}")
    assert response.status_code == 503
    assert response.json()["reason"] == "evaluation_unconfigured"


# --- results route -------------------------------------------------------------------------


def test_results_are_the_contract_document_verbatim_and_page() -> None:
    results = [make_result(i) for i in range(1, 5)]
    api = make_api(*results)
    first = api.get(ALICE, f"/domains/{FINANCE}/results", limit=3).json()
    assert [i["evaluation_id"] for i in first["items"]] == [f"eval:r-000{i}" for i in (1, 2, 3)]
    assert first["items"][0] == results[0].model_dump(mode="json", exclude_unset=True)
    second = api.get(ALICE, f"/domains/{FINANCE}/results", cursor=first["next_cursor"]).json()
    assert [i["evaluation_id"] for i in second["items"]] == ["eval:r-0004"]
    # Unknown stays null in the document, never 0.
    safety = next(s for s in first["items"][0]["scores"] if s["dimension"] == "safety")
    assert safety["value"] is None and safety["uncertainty"] == {"method": "not_estimable"}


def test_results_filters() -> None:
    api = make_api(
        make_result(1), make_result(2, subject_id="commercial:contoso:f:agent_version:b/v=1")
    )
    url = f"/domains/{FINANCE}/results"
    assert (
        len(
            api.get(ALICE, url, subject_id="commercial:contoso:f:agent_version:b/v=1").json()[
                "items"
            ]
        )
        == 1
    )
    assert api.get(ALICE, url, dimension="drift").json()["items"] == []
    assert api.get(ALICE, url, dimension="bogus").status_code == 422


# --- quality route -------------------------------------------------------------------------


def test_unknown_metrics_are_null_not_zero() -> None:
    api = make_api(make_result(1))
    body = api.get(ALICE, f"/domains/{FINANCE}/quality").json()
    safety = next(t for t in body["trends"] if t["dimension"] == "safety")["points"][0]
    assert safety["value"] is None
    assert safety["lower"] is None and safety["upper"] is None and safety["level"] is None
    assert safety["sample_size"] == 0
    grounded = next(t for t in body["trends"] if t["dimension"] == "groundedness")["points"][0]
    assert grounded["value"] == pytest.approx(0.82)
    assert (grounded["lower"], grounded["upper"], grounded["level"]) == (0.78, 0.86, 0.95)
    assert body["coverage"] == []
    assert body["drift_alerts"] == []


def test_judge_fields_and_calibration_state() -> None:
    api = make_api(
        make_result(1),
        make_result(
            2,
            judge=PROGRAMMATIC,
            calibration=None,
            scores=[score("tool_correctness", 0.9, 10, (0.8, 0.95))],
        ),
    )
    url = f"/domains/{FINANCE}/quality"
    body = api.get(ALICE, url).json()
    llm = next(t for t in body["trends"] if t["dimension"] == "groundedness")["points"][0]
    assert llm["judge"] == {
        "judge_kind": "llm_judge",
        "judge_model_id": JUDGE_CONFIG[0],
        "judge_model_version": "2026-08-01",
        "judge_prompt_version": "7",
        "program_version": None,
    }
    assert llm["calibration_state"] == "uncalibrated"  # no stored report
    prog = next(t for t in body["trends"] if t["dimension"] == "tool_correctness")["points"][0]
    assert prog["calibration_state"] == "not_applicable"
    assert prog["judge"]["program_version"] == "1" and prog["judge"]["judge_model_id"] is None

    api.h.app.state.evaluation_store = api.store
    import asyncio

    asyncio.run(
        api.store.put_calibration("commercial", "contoso", FINANCE, make_report("groundedness"))
    )
    asyncio.run(
        api.store.put_calibration(
            "commercial", "contoso", FINANCE, make_report("safety", state="uncalibrated")
        )
    )
    body = api.get(ALICE, url).json()
    states = {t["dimension"]: t["points"][0]["calibration_state"] for t in body["trends"]}
    assert states == {
        "groundedness": "calibrated",
        "safety": "uncalibrated",
        "tool_correctness": "not_applicable",
    }


def test_trends_bucket_by_utc_day_with_weighted_values() -> None:
    results = [
        make_result(
            1,
            completed_at="2026-10-10T23:30:00Z",
            scores=[score("groundedness", 0.8, 100, (0.7, 0.9))],
        ),
        make_result(
            2,
            completed_at="2026-10-10T01:00:00Z",
            scores=[score("groundedness", 0.6, 300, (0.5, 0.7))],
        ),
        make_result(
            3,
            completed_at="2026-10-11T00:00:00Z",
            scores=[score("groundedness", None, 0)],
        ),
    ]
    body = make_api(*results).get(ALICE, f"/domains/{FINANCE}/quality").json()
    (trend,) = body["trends"]
    day1, day2 = trend["points"]
    assert day1["bucket_start"] == "2026-10-10T00:00:00Z"
    assert day1["sample_size"] == 400
    assert day1["value"] == pytest.approx(0.65)
    assert day1["lower"] == pytest.approx(0.55) and day1["upper"] == pytest.approx(0.75)
    assert day2["bucket_start"] == "2026-10-11T00:00:00Z"
    assert day2["value"] is None and day2["sample_size"] == 0


def test_coverage_and_drift_alerts_come_from_the_store() -> None:
    import asyncio

    api = make_api(make_result(1))
    asyncio.run(
        api.store.put_coverage(
            SamplingCoverage(
                cloud="commercial",
                customer_id="contoso",
                domain_id=FINANCE,
                run_id="run1",
                stratum="agent-a",
                sampled=12,
                population=None,
                coverage_fraction=None,
                recorded_at=T,
            )
        )
    )
    alert = DriftAlert(
        dimension="groundedness",
        subject_id="commercial:contoso:foundry:agent_version:support-bot/v=3",
        detected_at="2026-10-19T00:00:00Z",
        statistic=0.4,
        threshold=0.25,
    )
    asyncio.run(api.store.put_drift_alert("commercial", "contoso", FINANCE, alert))
    asyncio.run(api.store.put_drift_alert("commercial", "contoso", OPERATIONS, alert))
    body = api.get(ALICE, f"/domains/{FINANCE}/quality").json()
    assert body["coverage"] == [
        {"stratum": "agent-a", "sampled": 12, "population": None, "coverage_fraction": None}
    ]
    assert body["drift_alerts"] == [alert.model_dump()]
    assert (
        api.get(ALICE, f"/domains/{FINANCE}/quality", subject_id="other").json()["drift_alerts"]
        == []
    )


def test_missing_label_counts() -> None:
    import asyncio

    api = make_api(make_result(1))
    url = f"/domains/{FINANCE}/quality"
    # Judged items exist but no report: labelled/missing unknown (null), never 0.
    assert api.get(ALICE, url).json()["missing_labels"] == {
        "judged": 400,
        "labelled": None,
        "missing": None,
    }
    asyncio.run(
        api.store.put_calibration(
            "commercial", "contoso", FINANCE, make_report(judged=10, labelled=6)
        )
    )
    assert api.get(ALICE, url).json()["missing_labels"] == {
        "judged": 10,
        "labelled": 6,
        "missing": 4,
    }
    # No judged items at all: zeros.
    empty = make_api(make_result(1, judge=PROGRAMMATIC, calibration=None))
    assert empty.get(ALICE, url).json()["missing_labels"] == {
        "judged": 0,
        "labelled": 0,
        "missing": 0,
    }


# --- pilot grounded rate -------------------------------------------------------------------


def _pilot_result(n: int, groundedness: float, size: int, dataset: str = "ds:pilot"):
    return make_result(
        n,
        dataset={"dataset_id": dataset, "dataset_version": "1"},
        scores=[score("groundedness", groundedness, size)],
    )


def test_pilot_rate_45_of_50_is_wilson() -> None:
    api = make_api(
        _pilot_result(1, 0.9, 50),
        _pilot_result(2, 0.1, 50, dataset="ds:not-pilot"),
        pilot=("ds:pilot",),
    )
    rate = api.get(ALICE, f"/domains/{FINANCE}/quality").json()["pilot_grounded_rate"]
    assert rate["n"] == 50
    assert rate["value"] == pytest.approx(0.9)
    assert rate["lower"] == pytest.approx(0.78640, abs=1e-4)
    assert rate["upper"] == pytest.approx(0.95652, abs=1e-4)
    assert rate["level"] == 0.95 and rate["method"] == "wilson_score"
    assert rate["target"] == 0.9 and rate["target_label"] == TARGET_LABEL
    expected = proportion_interval(45, 50, 0.95)
    assert (rate["lower"], rate["upper"]) == (expected.lower, expected.upper)


def test_pilot_rate_pools_results() -> None:
    rate = pilot_grounded_rate([_pilot_result(1, 1.0, 20), _pilot_result(2, 0.5, 20)], {"ds:pilot"})
    assert rate.n == 40 and rate.value == pytest.approx(0.75)


@pytest.mark.parametrize("pilot", [None, ()])
def test_empty_or_unset_pilot_set_is_not_estimable(pilot: tuple[str, ...] | None) -> None:
    api = make_api(_pilot_result(1, 0.9, 50), pilot=pilot)
    rate = api.get(ALICE, f"/domains/{FINANCE}/quality").json()["pilot_grounded_rate"]
    assert rate == {
        "value": None,
        "lower": None,
        "upper": None,
        "level": None,
        "n": 0,
        "method": "not_estimable",
        "target": 0.9,
        "target_label": TARGET_LABEL,
    }


def test_pilot_rate_ignores_unscored_groundedness() -> None:
    result = make_result(
        1,
        dataset={"dataset_id": "ds:pilot", "dataset_version": "1"},
        scores=[score("groundedness", None, 0)],
    )
    assert pilot_grounded_rate([result], {"ds:pilot"}).value is None


def test_no_guarantee_wording_in_response() -> None:
    api = make_api(_pilot_result(1, 0.9, 50), pilot=("ds:pilot",))
    text = api.get(ALICE, f"/domains/{FINANCE}/quality").text.lower()
    for word in ("guarantee", "sla"):
        assert word not in text


def test_compute_quality_on_empty_input() -> None:
    out = compute_quality([], [], [], [], set())
    assert out.trends == [] and out.pilot_grounded_rate.value is None
    assert out.missing_labels.judged == 0
