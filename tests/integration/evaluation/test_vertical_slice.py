"""Vertical slice, in process (PRP-16 item 6).

sandbox benchmark data (50-item groundedness pilot set, rubric, judge configs, recorded judge
fixtures, versioned human labels) -> worker pipeline (offline run, calibration, online run, drift)
-> ``InMemoryEvaluationStore`` -> the real API app built by ``create_app`` with the default
routers, over HTTP (dev-issuer tokens, in-memory policy store, Government-bound).

In process: no compose, no network (outbound connects are blocked below), no cloud, so this is NOT
marked ``integration`` and runs in CI. The capability matrix is the SHIPPED one: the only
Commercial Foundry row is ``unverified`` (G01 OPEN), so the Commercial judge is disabled and the
pilot set runs on the Government judge, whose rows are ``available``. What this does NOT prove: a
live judge (G16), a Cosmos evaluation store, runtime hosting, the Azure blob archive reader.
"""

from __future__ import annotations

import asyncio
import socket
from collections import Counter
from collections.abc import Iterator
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from neurosphere_api.evaluation import PREFIX
from neurosphere_contracts.evaluation.v1.evaluation_result import EvaluationResult
from neurosphere_core.evaluation.calibration import proportion_interval
from neurosphere_core.evaluation.registry import check_result_references
from neurosphere_core.evaluation.store import InMemoryEvaluationStore
from neurosphere_workers.evaluation.budget import BudgetLimits
from neurosphere_workers.evaluation.service import EvaluationService
from neurosphere_workers.evaluation.source import InMemoryRecordSource, NdjsonRecordSource

from sandbox.evaluation.loader import PILOT_DATASET_ID

from . import support as sp

_LOOPBACK = {"127.0.0.1", "::1", "localhost"}


@pytest.fixture(scope="module", autouse=True, name="no_network")
def _no_network() -> Iterator[None]:
    """Fail any non-loopback connect (asyncio itself uses loopback sockets on Windows)."""
    real = socket.socket.connect

    def guarded(self: socket.socket, address: Any) -> None:
        host = address[0] if isinstance(address, tuple) else address
        if host not in _LOOPBACK:
            raise AssertionError(f"network call attempted: {address!r}")
        real(self, address)

    patch = pytest.MonkeyPatch()
    patch.setattr(socket.socket, "connect", guarded)
    yield
    patch.undo()


@pytest.fixture(scope="module", name="s")
def slice_(no_network: None) -> sp.Slice:
    return asyncio.run(sp.run_slice())


@pytest.fixture(scope="module", name="h")
def harness_(s: sp.Slice) -> sp.GovHarness:
    return sp.two_domain_harness(s.store)


def _get(h: sp.GovHarness, who: str, domain: str, tail: str, **params: Any) -> Any:
    return h.client.get(
        f"{PREFIX}/domains/{domain}/{tail}", params=params or None, headers=h.auth(who)
    )


def _all_results(h: sp.GovHarness, who: str, domain: str) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    cursor: str | None = None
    while True:
        extra = {"cursor": cursor} if cursor else {}
        response = _get(h, who, domain, "results", limit=50, **extra)
        assert response.status_code == 200, response.text
        body = response.json()
        items.extend(body["items"])
        cursor = body["next_cursor"]
        if cursor is None:
            return items


# --- the pilot rate ----------


def test_pilot_rate_is_present_with_a_wilson_interval_and_the_exact_target_label(
    s: sp.Slice, h: sp.GovHarness
) -> None:
    response = _get(h, sp.ALICE, sp.FIN, "quality")
    assert response.status_code == 200, response.text
    pilot = response.json()["pilot_grounded_rate"]
    scored = s.summary.offline.results[0].scores[0]
    assert pilot["n"] == scored.sample_size == 40  # 50 items, 8 restricted skipped, 2 abstained
    assert pilot["method"] == "wilson_score" and pilot["level"] == 0.95
    successes = round((scored.value or 0.0) * pilot["n"])
    expected = proportion_interval(successes, pilot["n"], 0.95)
    assert pilot["value"] == pytest.approx(successes / pilot["n"])
    assert (pilot["lower"], pilot["upper"]) == pytest.approx((expected.lower, expected.upper))
    assert pilot["lower"] < pilot["value"] < pilot["upper"]
    assert pilot["target"] == 0.9
    assert pilot["target_label"] == "pilot-set target: at least 90%"
    assert "guarantee" not in response.text.lower()


def test_restricted_pilot_items_produced_zero_judge_calls(s: sp.Slice) -> None:
    pilot = sp.pilot_dataset(s.registry)
    restricted = {i.item_id for i in pilot.items if i.classification == "restricted"}
    assert len(restricted) == 8
    assert not ({c.item_id for c in s.fixture.calls} & restricted)
    assert s.fixture.call_count == len(pilot.items) - len(restricted) == 42
    report = s.summary.offline
    assert report.skip_counts == {"judge_not_approved": 8}
    skipped = [o for o in report.outcomes if o.status == "skipped"]
    assert {o.item_id for o in skipped} == restricted
    assert all(o.input_tokens is None and o.cost is None for o in skipped)


def test_calibration_is_stored_under_the_item4_key_so_the_judge_is_not_uncalibrated(
    s: sp.Slice, h: sp.GovHarness
) -> None:
    assert s.summary.calibrations_stored == 1 and not s.summary.uncalibrated_judges
    body = _get(h, sp.ALICE, sp.FIN, "quality").json()
    llm_points = [
        p
        for t in body["trends"]
        if t["dimension"] == "groundedness"
        for p in t["points"]
        if p["judge"]["judge_kind"] == "llm_judge"
    ]
    assert [p["calibration_state"] for p in llm_points] == ["calibrated"]
    assert llm_points[0]["judge"]["judge_model_id"].endswith(":judge-government")
    assert body["missing_labels"] == {"judged": 40, "labelled": 40, "missing": 0}
    # Negative control: the same results without their calibration report render uncalibrated.
    bare = InMemoryEvaluationStore(s.summary.offline.results)
    other = sp.two_domain_harness(bare)
    body = _get(other, sp.ALICE, sp.FIN, "quality").json()
    grounded = next(t for t in body["trends"] if t["dimension"] == "groundedness")
    assert [p["calibration_state"] for p in grounded["points"]] == ["uncalibrated"]


def test_coverage_shows_the_unjudged_restricted_stratum_as_zero_not_unknown(
    h: sp.GovHarness,
) -> None:
    coverage = {c["stratum"]: c for c in _get(h, sp.ALICE, sp.FIN, "quality").json()["coverage"]}
    restricted = coverage["finance/groundedness/restricted"]
    assert (restricted["sampled"], restricted["population"]) == (0, 8)
    assert restricted["coverage_fraction"] == 0.0
    public = coverage["finance/groundedness/public"]
    assert (public["sampled"], public["population"], public["coverage_fraction"]) == (16, 16, 1.0)


# --- drift ----------


def test_seeded_shift_raises_one_stored_alert_and_the_stable_window_none(
    s: sp.Slice, h: sp.GovHarness
) -> None:
    states = [d.state for d in s.summary.drift]
    assert states == ["stable", "drift"]
    assert s.summary.drift_alerts_stored == 1
    alerts = _get(h, sp.ALICE, sp.FIN, "quality").json()["drift_alerts"]
    assert len(alerts) == 1
    assert alerts[0]["dimension"] == "groundedness" and alerts[0]["subject_id"] == sp.PILOT_SUBJECT
    assert alerts[0]["statistic"] >= alerts[0]["threshold"] == 0.25
    assert _get(h, sp.BOB, sp.OPS, "quality").json()["drift_alerts"] == []


# --- authorization ----------


def test_a_caller_never_sees_another_domain(s: sp.Slice, h: sp.GovHarness) -> None:
    for tail in ("quality", "results"):
        assert _get(h, sp.ALICE, sp.OPS, tail).status_code == 403
        assert _get(h, sp.BOB, sp.FIN, tail).status_code == 403
    alice = _all_results(h, sp.ALICE, sp.FIN)
    bob = _all_results(h, sp.BOB, sp.OPS)
    assert alice and bob
    assert {r["domain_id"] for r in alice} == {sp.FIN}
    assert {r["domain_id"] for r in bob} == {sp.OPS}
    assert not ({r["evaluation_id"] for r in alice} & {r["evaluation_id"] for r in bob})
    assert PILOT_DATASET_ID not in {r["dataset"]["dataset_id"] for r in bob}
    assert h.client.get(f"{PREFIX}/domains/{sp.FIN}/quality").status_code == 401


def test_every_stored_result_validates_and_references_registered_versions(
    s: sp.Slice, h: sp.GovHarness
) -> None:
    checked = 0
    for who, domain in ((sp.ALICE, sp.FIN), (sp.BOB, sp.OPS)):
        for item in _all_results(h, who, domain):
            result = EvaluationResult.model_validate(item)
            check_result_references(result, s.registry)
            assert result.judge.judge_kind != "human"
            checked += 1
    assert checked == s.summary.results_stored == len(s.summary.result_ids) == 9


# --- online ----------


def test_online_results_are_metadata_only_with_groundedness_unknown(
    s: sp.Slice, h: sp.GovHarness
) -> None:
    online = s.summary.online
    assert online is not None and online.mode == "online_sampled"
    assert online.limited_dimensions == {"groundedness": "bodies_not_archived"}
    assert online.excluded_counts == {"not_scorable_span": 20}
    assert online.evaluated_total == online.sampled_total == 160
    body = _get(h, sp.BOB, sp.OPS, "quality").json()
    trends = {t["dimension"]: t for t in body["trends"]}
    assert {"task_success", "tool_correctness", "groundedness"} <= set(trends)
    for dimension in ("task_success", "tool_correctness"):
        assert {p["calibration_state"] for p in trends[dimension]["points"]} == {"not_applicable"}
        assert all(p["value"] is not None for p in trends[dimension]["points"])
    for point in trends["groundedness"]["points"]:
        assert point["value"] is None and point["lower"] is None and point["sample_size"] == 0
    # Bob's quality has no pilot data: unknown, not 0.
    pilot = body["pilot_grounded_rate"]
    assert pilot["value"] is None and pilot["n"] == 0 and pilot["method"] == "not_estimable"


async def test_online_llm_judge_receives_only_approved_classifications(s: sp.Slice) -> None:
    """The guard on the online path: restricted and null-classified items reach no judge."""
    registry = sp.build_registry()
    registry.datasets.register(sp.frame_dataset())
    double = sp.CountingLlm()
    service = EvaluationService(
        judge=double, matrix=s.matrix, registry=registry, ledger=sp.ledger(), clock=sp.clock
    )
    config = sp.online_config(registry, run_id="online-llm-guard", llm=True)
    report = await service.run_online(InMemoryRecordSource(sp.synthetic_archive()), config)
    sent = Counter(c.classification for c in double.calls)
    assert set(sent) == {"public", "internal", "cui"}
    assert report.skip_counts == {"judge_not_approved": 64}  # restricted + null, 2 x 2 x 2 x 4 x 2
    assert len(double.calls) == report.evaluated_total == 96
    # No human labels exist for the metadata dimensions, so the LLM-judged results are not emitted.
    assert report.results == () and report.uncalibrated_judges


# --- budget ----------


def test_a_budget_limited_run_reports_budget_exhausted_with_the_coverage_achieved() -> None:
    limited = asyncio.run(
        sp.run_slice(
            budget=BudgetLimits(tokens=6_000, cost=Decimal("1")), with_online=False, drift=False
        )
    )
    report = limited.summary.offline
    assert report.status == "budget_exhausted"
    assert (report.budget_exhausted_reason or "").startswith("run_tokens")
    assert 0 < report.evaluated_total < 42
    refused = report.skip_counts.get(
        "judge_not_approved", 0
    )  # restricted items met before the stop
    assert report.sampled_total == report.evaluated_total + refused + report.unevaluated_total
    assert report.skip_counts["budget_exhausted"] == report.unevaluated_total
    assert sum(c.evaluated for c in report.coverage) == report.evaluated_total
    assert limited.fixture.call_count == report.evaluated_total  # no call past the budget
    assert sum(u.input_tokens + u.output_tokens for u in report.usage) <= 6_000


# --- capability-matrix honesty ----------


def test_the_commercial_judge_is_disabled_by_the_shipped_matrix_and_nothing_is_judged() -> None:
    """Measured finding: the only Commercial Foundry row in the shipped matrix is ``unverified``
    (G01 OPEN), so the Commercial judge is disabled with a reason and the pilot set is not run
    there. Nothing is rerouted to the Government judge and nothing is invented."""
    commercial = asyncio.run(sp.run_slice(cloud="commercial", with_online=False, drift=False))
    report = commercial.summary.offline
    assert report.skip_counts == {"judge_unavailable": 50}
    assert commercial.fixture.call_count == 0
    assert report.evaluated_total == 0 and commercial.summary.results_stored == 0
    detail = next(o.detail for o in report.outcomes if o.detail)
    assert "unverified" in detail and "foundry.base.commercial.global.any" in detail
    assert commercial.summary.calibration_skipped


async def test_sandbox_telemetry_carries_no_classification_so_online_is_fully_skipped(
    s: sp.Slice, tmp_path: Path
) -> None:
    """Fail-closed rules: a missing classification is restricted, so against an LLM judge every
    online item built from the sandbox telemetry is skipped. This is reported, not changed."""
    path = sp.generate_government_telemetry(tmp_path / "telemetry-out")
    lines = [ln for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert lines and all('"classification"' not in ln for ln in lines)
    registry = sp.build_registry()
    registry.datasets.register(sp.frame_dataset())
    double = sp.CountingLlm()
    service = EvaluationService(
        judge=double, matrix=s.matrix, registry=registry, ledger=sp.ledger(), clock=sp.clock
    )
    config = sp.online_config(registry, run_id="online-sandbox", llm=True)
    report = await service.run_online(NdjsonRecordSource(path), config)
    assert report.sampled_total > 0
    assert report.skip_counts == {"judge_not_approved": report.sampled_total}
    assert report.evaluated_total == 0 and not double.calls and report.results == ()
