"""Profile definitions, scenarios and evidence writer (PRP-21 item 1). Runs in CI.

Must not import locust: importing it gevent-monkeypatches the process and would break the shared
asyncio pytest session. ``locustfile.py`` is the only module that imports it and no test imports
that file. Enterprise and stress are never started here.
"""

from __future__ import annotations

import json
import statistics
import subprocess
import sys
from collections import Counter
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from neurosphere_api.app import create_app
from neurosphere_api.ingest import (
    IngestSettings,
    InMemoryPublisher,
    StaticProducerRegistry,
    build_service,
    configure_ingest,
    hash_secret,
)
from neurosphere_api.ingest.auth import ProducerRegistration
from neurosphere_contracts.telemetry.v1.telemetry_event import TelemetryEvent
from neurosphere_core.cloud import Settings

from .definitions import (
    ENTERPRISE,
    PILOT,
    PROFILES,
    SCENARIOS,
    STRESS,
    TargetRequiredError,
    domain_weights,
    resolve_run,
)
from .evidence import Tally, build_evidence, evaluate_thresholds, write_evidence
from .scenarios import RequestPlanner, make_producers

RUN_SCRIPT = Path(__file__).resolve().parent / "run_profile.py"


def test_locust_is_not_imported_by_the_plain_modules() -> None:
    assert "locust" not in sys.modules


def test_profile_numbers_match_the_prd() -> None:
    assert (PILOT.agents, PILOT.sustained_events_per_second) == (1_000, 1_000)
    assert (ENTERPRISE.agents, ENTERPRISE.sustained_events_per_second) == (100_000, 10_000)
    assert (STRESS.entities, STRESS.relationships) == (1_000_000, 10_000_000)
    assert (STRESS.sustained_events_per_second, STRESS.burst_events_per_second) == (50_000, 150_000)
    assert STRESS.subject_to == "partition/cost validation"
    assert set(PROFILES) == {"pilot", "enterprise", "stress"}


def test_thresholds_follow_the_profile_rate() -> None:
    for profile in PROFILES.values():
        assert (
            profile.thresholds.min_achieved_events_per_second == profile.sustained_events_per_second
        )


def test_only_the_pilot_has_a_default_target_and_it_is_local() -> None:
    assert PILOT.requires_explicit_target is False
    assert PILOT.default_host == "http://localhost:8000"
    for profile in (ENTERPRISE, STRESS):
        assert profile.requires_explicit_target is True
        assert profile.default_host is None


@pytest.mark.parametrize("name", ["enterprise", "stress"])
def test_enterprise_and_stress_refuse_without_a_target(name: str) -> None:
    with pytest.raises(TargetRequiredError):
        resolve_run(name)
    with pytest.raises(TargetRequiredError):
        resolve_run(name, host="https://ingest.example.invalid")  # no environment label
    with pytest.raises(TargetRequiredError):
        resolve_run(name, environment_label="a sized environment")  # no host


@pytest.mark.parametrize("name", ["enterprise", "stress"])
def test_enterprise_and_stress_run_only_with_host_and_label(name: str) -> None:
    plan = resolve_run(
        name,
        host="https://ingest.example.invalid",
        environment_label="operator environment",
        duration_seconds=30,
    )
    assert plan.profile.name == name
    assert plan.duration_seconds == 30
    assert plan.environment_label == "operator environment"
    assert "duration_seconds" in plan.overrides


@pytest.mark.parametrize("bad", ["", "localhost:8000", "ftp://host", "http://"])
def test_malformed_hosts_are_rejected(bad: str) -> None:
    with pytest.raises((ValueError, TargetRequiredError)):
        resolve_run("enterprise", host=bad, environment_label="x")


def test_pilot_resolves_to_local_compose_with_the_bounded_label() -> None:
    plan = resolve_run("pilot")
    assert plan.host == "http://localhost:8000"
    assert "bounded feasibility only" in plan.environment_label
    assert "not capacity evidence (G12)" in plan.environment_label
    assert plan.requests_per_second == PILOT.sustained_events_per_second / PILOT.batch_size


@pytest.mark.parametrize("name", ["enterprise", "stress"])
def test_cli_refuses_without_a_target(name: str) -> None:
    done = subprocess.run(
        [sys.executable, str(RUN_SCRIPT), name, "--dry-run"],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert done.returncode == 2
    assert "refused" in done.stderr


@pytest.mark.parametrize("multiple", [1.0, 10.0, 50.0, 200.0])
def test_skew_multiple_is_configurable_against_the_median(multiple: float) -> None:
    weights = domain_weights(20, multiple)
    assert weights[0] == multiple * statistics.median(weights)


def test_skew_needs_a_non_hot_median_and_a_sane_multiple() -> None:
    with pytest.raises(ValueError, match="at least 3"):
        domain_weights(2, 10)
    with pytest.raises(ValueError, match=">= 1"):
        domain_weights(10, 0.5)


def _planner(multiple: float = 50.0, seed: int = 1):
    producers = make_producers(PILOT, "unit")
    return RequestPlanner(
        PILOT, producers, run_id="unit", skew_multiple=multiple, seed=seed
    ), producers


def test_baseline_skew_concentrates_on_one_domain_at_the_configured_multiple() -> None:
    planner, _ = _planner(multiple=50.0)
    counts: Counter[str] = Counter()
    for _ in range(200):
        counts.update(planner.build("baseline_skew").domains)
    median = statistics.median(counts.get(d, 0) for d in planner.domain_ids)
    assert counts.most_common(1)[0][0] == planner.hot_domain
    assert counts[planner.hot_domain] / median > 20  # ~50x expected; wide margin for sampling


def test_skew_of_one_is_not_skewed() -> None:
    planner, _ = _planner(multiple=1.0)
    counts: Counter[str] = Counter()
    for _ in range(400):
        counts.update(planner.build("baseline_skew").domains)
    assert counts[planner.hot_domain] / statistics.median(counts.values()) < 2


def test_hot_key_uses_one_source_domain_and_agent() -> None:
    planner, producers = _planner()
    req = planner.build("hot_key")
    assert set(req.domains) == {planner.hot_domain}
    assert set(req.agents) == {planner.hot_agent}
    assert req.producer is producers[0]
    events = json.loads(req.body)
    assert {e["data"]["source_id"] for e in events} == {producers[0].sources[0]}


def test_fan_out_spans_many_domains_in_one_batch() -> None:
    planner, _ = _planner()
    req = planner.build("fan_out")
    assert len(set(req.domains)) == min(PILOT.fan_out_width, PILOT.domains)
    assert len(set(req.agents)) == PILOT.batch_size


def test_multi_domain_producer_is_permission_heavy() -> None:
    planner, producers = _planner()
    req = planner.build("multi_domain")
    assert len(req.producer.sources) == PILOT.multi_domain_sources
    sources = {e["data"]["source_id"] for e in json.loads(req.body)}
    assert len(sources) == min(PILOT.batch_size, PILOT.multi_domain_sources)
    assert sources <= set(req.producer.sources)
    assert req.producer is producers[-1]


def test_secrets_are_generated_per_run() -> None:
    first = make_producers(PILOT, "a")
    second = make_producers(PILOT, "a")
    assert first[0].secret != second[0].secret
    assert hash_secret(first[0].secret) != first[0].secret


def test_every_scenario_is_accepted_by_the_real_ingest_edge() -> None:
    """The generated requests are valid for the product's ingest edge (in-process, no emulator)."""
    planner, producers = _planner()
    registry = StaticProducerRegistry(
        [
            ProducerRegistration.model_validate(p.registration(hash_secret(p.secret)))
            for p in producers
        ]
    )
    settings = Settings(env="local")
    publisher = InMemoryPublisher()
    service = build_service(
        settings,
        IngestSettings(rate_limit_rps=100_000, rate_limit_burst=100_000),
        publisher,
        registry=registry,
    )
    app = create_app(settings)
    configure_ingest(app, service)
    client = TestClient(app)
    accepted = 0
    for scenario in SCENARIOS:
        req = planner.build(scenario)
        resp = client.post(
            req.path,
            content=req.body,
            headers={"Authorization": req.producer.authorization, "Content-Type": req.content_type},
        )
        assert resp.status_code == 202, (scenario, resp.text)
        body = resp.json()
        assert body["rejected"] == [], (scenario, body)
        assert body["accepted"] == req.event_count, scenario
        accepted += body["accepted"]
    assert len(publisher.messages) == accepted


def test_cloudevent_payloads_validate_against_the_telemetry_contract() -> None:
    planner, _ = _planner()
    for scenario in ("baseline_skew", "hot_key", "fan_out", "multi_domain"):
        for event in json.loads(planner.build(scenario).body):
            data = dict(event["data"])
            TelemetryEvent.model_validate(data)


def test_unmeasured_thresholds_fail_and_measured_ones_are_evaluated() -> None:
    plan = resolve_run("pilot")
    empty = evaluate_thresholds(plan, {})
    assert [row["passed"] for row in empty] == [False, False, False]
    good = evaluate_thresholds(
        plan,
        {
            "achieved_events_per_second": 1200.0,
            "error_ratio": 0.0,
            "latency_ms": {"p95": 150.0},
        },
    )
    assert all(row["passed"] for row in good)
    assert all(row["provisional"] for row in good)
    slow = evaluate_thresholds(
        plan,
        {"achieved_events_per_second": 400.0, "error_ratio": 0.0, "latency_ms": {"p95": 150.0}},
    )
    assert [row["passed"] for row in slow] == [False, True, True]


def test_evidence_document_shape_and_honesty_fields(tmp_path: Path) -> None:
    plan = resolve_run("pilot")
    tally = Tally()
    tally.record(
        scenario="baseline_skew",
        producer_id="p0",
        domains=("d0", "d0", "d1"),
        agents=("a0", "a1", "a2"),
        status=202,
        accepted=3,
    )
    tally.record(
        scenario="hot_key",
        producer_id="p0",
        domains=("d0",),
        agents=("a0",),
        status=503,
        accepted=0,
        error_type="http_503",
    )
    doc = build_evidence(
        plan,
        tally,
        duration_seconds=2.0,
        latency_ms={"p50": 10.0, "p95": 20.0, "p99": 30.0, "max": 40.0},
        per_scenario_latency_ms={},
        method="unit test",
    )
    assert doc["profile"] == "pilot"
    assert doc["not_evidence_for"] == ["enterprise", "stress"]
    assert doc["environment_label"] == plan.environment_label
    assert doc["measured"]["achieved_events_per_second"] == 1.5
    assert doc["measured"]["error_counts_by_type"] == {"http_503": 1}
    assert doc["measured"]["error_ratio"] == 0.5
    assert doc["thresholds_all_passed"] is False
    assert {row["name"] for row in doc["thresholds"]} == {
        "achieved_events_per_second",
        "error_ratio",
        "request_latency_p95_ms",
    }
    assert doc["profile_definition"]["catalog_scale_driven_by_this_suite"] is False
    assert any("OPEN" in line for line in doc["open"])
    path = write_evidence(tmp_path, doc)
    assert path.name == f"pilot-{doc['date']}.json"
    assert json.loads(path.read_text(encoding="utf-8"))["profile"] == "pilot"


def test_cloudevent_type_matches_the_product_constant() -> None:
    from neurosphere_core.payload import CLOUDEVENT_TYPE_TELEMETRY

    from .scenarios import CLOUDEVENT_TYPE_TELEMETRY as LOCAL_TYPE

    assert LOCAL_TYPE == CLOUDEVENT_TYPE_TELEMETRY
