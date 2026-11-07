"""Per-step create/found expectations on the awaiting-confirmation view (PRP-34 item 8).

The steps are an additive, read-only preview: they never change the confirmation hash, appear
only while the intent awaits confirmation, and a failing plan leaves the view without them.
"""

from __future__ import annotations

from typing import Any

from action_plane_harness import ALICE, Api, make_api  # pyright: ignore[reportMissingImports]
from neurosphere_api.actions.models import PlanStepView
from neurosphere_core.errors import DependencyTransientError

STEPS = [
    PlanStepView(
        resource_type="product",
        name="products/finance-analyst",
        expected="create",
        operation="upsert",
        payload_digest_prefix="abababababab",
    ),
    PlanStepView(
        resource_type="product_api_link",
        name="products/finance-analyst/apiLinks/llm",
        expected="found",
        operation="upsert",
        payload_digest_prefix=None,
    ),
]


def _offer(api: Api, steps: Any = STEPS, error: Exception | None = None) -> None:
    async def plan_steps(request: Any) -> Any:
        if error is not None:
            raise error
        return steps

    api.connector.plan_steps = plan_steps  # type: ignore[attr-defined]


def test_present_confirmation_and_get_report_the_steps_without_touching_the_hash() -> None:
    api = make_api()
    baseline = make_api().presented()["intent"]["confirmation_hash"]
    _offer(api)
    view = api.presented()
    assert view["intent"]["state"] == "awaiting_confirmation"
    assert view["intent"]["confirmation_hash"] == baseline
    assert [(s["name"], s["expected"]) for s in view["plan_steps"]] == [
        ("products/finance-analyst", "create"),
        ("products/finance-analyst/apiLinks/llm", "found"),
    ]
    assert view["plan_steps"][0]["payload_digest_prefix"] == "abababababab"
    fetched = api.get_intent(view["intent"]["intent_id"]).json()
    assert fetched["plan_steps"] == view["plan_steps"]


def test_steps_are_absent_before_confirmation_and_for_connectors_without_a_plan() -> None:
    api = make_api()
    _offer(api)
    assert "plan_steps" not in api.validated()
    assert "plan_steps" not in make_api().presented()


def test_a_failing_plan_leaves_the_view_without_steps() -> None:
    api = make_api()
    _offer(api, error=DependencyTransientError("arm down", reason="arm_unavailable"))
    view = api.presented()
    assert view["intent"]["state"] == "awaiting_confirmation"
    assert "plan_steps" not in view
    assert api.get_intent(view["intent"]["intent_id"], ALICE).status_code == 200
