"""The ``governance`` runtime builder (PRP-105 item 6): settings, refusals, status.

* the in-memory backend is refused outside ``NS_ENV=local`` (the app does not start);
* ``NS_GOVPOLICY_ENABLED=false`` -> component ``disabled`` and every route 503
  ``capability_unavailable``;
* missing upstream pieces or Cosmos -> ``disabled`` with a reason code, never a crash;
* ``GET /status`` reports evaluator availability per rule kind (criterion 10) and the latest run.
"""

from __future__ import annotations

import pytest
from govpolicy_api_harness import (  # pyright: ignore[reportMissingImports]
    BASE,
    FINANCE,
    INVESTIGATOR,
    OPERATIONS,
    STEWARD,
    VIEWER,
    GovWorld,
    compose_governance,
)
from neurosphere_api.runtime.builders import default_builders
from neurosphere_api.runtime.builders import governance as builder
from neurosphere_api.runtime.status import OPTIONAL_COMPONENTS
from neurosphere_core.cloud import CloudName, Settings
from neurosphere_core.governance.policy import EvaluationStatus
from runtime_api.runtime_helpers import compose  # pyright: ignore[reportMissingImports]

UNAVAILABLE = {"budget", "required_attestation", "identity_entitlement", "content_rule"}


def test_builder_is_optional_and_runs_after_interactions_before_admin() -> None:
    names = [spec.name for spec in default_builders()]
    assert names.index("interactions") < names.index("governance") == names.index("admin") - 1
    assert names[-1] == "analytics"
    assert "governance_policy" in OPTIONAL_COMPONENTS
    assert builder.BUILDER.components == ("governance_policy",)


def test_memory_backend_outside_local_refuses_to_start(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NS_ENV", "dev")
    monkeypatch.setenv("NS_GOVPOLICY_BACKEND", "memory")
    with pytest.raises(builder.GovPolicyMemoryNotLocalError) as refused:
        compose(
            None,
            builders=(builder.BUILDER,),
            settings=Settings(env="dev", cloud=CloudName.COMMERCIAL),
        )
    assert refused.value.reason == "govpolicy_memory_not_local"


def test_memory_backend_under_local_builds_the_plane(monkeypatch: pytest.MonkeyPatch) -> None:
    parts = compose_governance(monkeypatch, NS_GOVPOLICY_EXCEPTION_MAX_DAYS="30")
    assert parts.composed.registry.get("governance_policy").state == "ok"
    plane = parts.composed.app.state.governance_policy
    assert plane.backend == "memory"
    assert plane.exception_max_days == 30
    assert plane.exception_requester.max_days == 30
    assert parts.composed.app.state.governance_policy_off_reason is None


def test_disabled_component_answers_503_capability_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    parts = compose_governance(monkeypatch, NS_GOVPOLICY_ENABLED="false")
    status = parts.composed.registry.get("governance_policy")
    assert status.state == "disabled"
    assert not status.blocks_readiness
    assert parts.composed.app.state.governance_policy is None
    assert parts.composed.app.state.governance_policy_off_reason == "setting_off"
    client = parts.composed.client()
    for path in ("/status", f"/domains/{FINANCE}/policies", f"/domains/{FINANCE}/violations"):
        response = client.get(BASE + path, headers=parts.composed.auth(VIEWER))
        assert response.status_code == 503, (path, response.text)
        assert response.json()["reason"] == "capability_unavailable"


def test_missing_upstream_pieces_disable_with_a_reason(monkeypatch: pytest.MonkeyPatch) -> None:
    parts = compose_governance(monkeypatch, data=False)
    assert parts.composed.registry.get("governance_policy").state == "disabled"
    assert parts.composed.app.state.governance_policy_off_reason == "audit_unavailable"


def test_cosmos_backend_without_cosmos_is_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    parts = compose_governance(monkeypatch, NS_GOVPOLICY_BACKEND="cosmos")
    assert parts.composed.registry.get("governance_policy").state == "disabled"
    assert parts.composed.app.state.governance_policy_off_reason == "cosmos_unconfigured"


def test_invalid_settings_fail_the_component(monkeypatch: pytest.MonkeyPatch) -> None:
    parts = compose_governance(monkeypatch, NS_GOVPOLICY_EXCEPTION_MAX_DAYS="400")
    status = parts.composed.registry.get("governance_policy")
    assert (status.state, status.code) == ("failed", "govpolicy_settings_invalid")


@pytest.fixture
def world(monkeypatch: pytest.MonkeyPatch) -> GovWorld:
    return GovWorld.build(monkeypatch)


def test_registry_holds_the_builtin_kinds_and_reports_the_rest(world: GovWorld) -> None:
    """``interaction_finding_reader`` is unbound until PRP-104 item 8: no ``content_rule``."""
    registry = world.plane.registry
    assert set(registry.available_kinds) == {
        "model_allow_list",
        "data_sensitivity_access",
        "residency",
        "required_owner",
        "required_approval",
        "registration_required",
    }
    assert registry.unavailable_reason("content_rule") == "finding_reader_unbound"


async def test_status_reports_evaluators_and_the_latest_run(world: GovWorld) -> None:
    response = world.call("GET", VIEWER, "/status")
    assert response.status_code == 200, response.text
    body = response.json()
    kinds = {k["kind"]: k for k in body["rule_kinds"]}
    assert {k for k, v in kinds.items() if v["status"] == "evaluator_unavailable"} == UNAVAILABLE
    assert kinds["content_rule"]["reason"] == "finding_reader_unbound"
    assert kinds["residency"] == {"kind": "residency", "status": "available", "reason": None}
    assert body["runs"] == [{"domain_id": FINANCE, "status": None}]
    assert {p["point"] for p in body["points"]} >= {"gateway", "sdk", "registration"}

    await world.plane.statuses.record(
        EvaluationStatus.model_validate(
            {
                "run_id": "00000000-0000-4000-8000-0000000000cc",
                "cloud": "commercial",
                "customer_id": "contoso",
                "domain_id": FINANCE,
                "trigger": "interval",
                "state": "truncated",
                "started_at": "2027-01-15T08:00:00Z",
                "finished_at": "2027-01-15T08:00:05Z",
                "correlation_id": "corr-test-run",
            }
        )
    )
    runs = world.call("GET", STEWARD, "/status").json()["runs"]
    assert runs[0]["domain_id"] == FINANCE
    assert runs[0]["status"]["state"] == "truncated"
    assert "govpolicy.status_read" in world.operations()


def test_status_lists_only_domains_the_caller_can_read(world: GovWorld) -> None:
    runs = world.call("GET", STEWARD, "/status").json()["runs"]
    assert OPERATIONS not in {r["domain_id"] for r in runs}
    assert world.call("GET", INVESTIGATOR, "/status").status_code == 403
