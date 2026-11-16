"""PRP-54 item 5: the approval and read-back-verify chain over a registry filled from STORED
write-target entries (not the hand-built connector the vertical slice uses).

In-memory stores plus the real registration code, the real executor and the scripted ARM that
mutates its own state, so a swap is proven by reading the target back. Not run against the
Cosmos emulator (no Cosmos is involved in this chain); unmarked, so it runs in CI. Every refusal
asserts the connector was never called (zero ARM writes).
"""

from __future__ import annotations

from typing import Any

import pytest
from neurosphere_workers.runtime.factories import WriteTargetEntry

from .support import ALICE, BOB, DAVE, FAKES, Slice, make_slice, problem

ACCOUNT_ID = (
    f"/subscriptions/{FAKES.SUB}/resourceGroups/rg-ai"
    "/providers/Microsoft.CognitiveServices/accounts/acct1"
)


@pytest.fixture(autouse=True)
def _foundry_region(monkeypatch: pytest.MonkeyPatch) -> None:
    # The stored entry carries no region; the Models read takes it from the env fallback.
    monkeypatch.setenv("NS_FOUNDRY_LOCATION", "eastus2")


def _stored() -> Slice:
    return make_slice(stored_entries=[WriteTargetEntry("foundry", ACCOUNT_ID)])


def _model(s: Slice) -> tuple[str, str]:
    model = s.arm.state["properties"]["model"]
    return model["name"], model["version"]


def _intent_id(view: dict[str, Any]) -> str:
    return view["intent"]["intent_id"]


def test_the_stored_entry_registers_the_swap_connector() -> None:
    s = _stored()
    assert s.registry.names() == ("foundry-model-swap",)
    assert s.advisory is False


def test_model_swap_from_a_stored_entry_changes_the_target_and_verifies() -> None:
    s = _stored()
    assert _model(s) == ("gpt-4o", "2024-08-06")
    view = s.awaiting_approval()
    assert s.arm.puts == []
    approved = s.approve(view, who=BOB)
    assert approved.status_code == 200, approved.text
    assert s.arm.puts == []  # approval is not execution
    report = s.execute(view)
    assert (report.outcome, report.state) == ("succeeded", "succeeded")
    # Read back from the (fake) target, not from catalog metadata.
    assert _model(s) == ("gpt-4.1", "2025-04-14")
    assert len(s.arm.puts) == 1


def test_self_approval_stops_before_the_connector() -> None:
    s = _stored()
    view = s.awaiting_approval()
    own = s.approve(view, who=ALICE)
    assert own.status_code == 403
    assert problem(own)["reason"] == "self_approval_forbidden"
    assert s.arm.puts == []
    assert _model(s) == ("gpt-4o", "2024-08-06")


def test_a_missing_approval_never_reaches_the_connector() -> None:
    s = _stored()
    view = s.awaiting_approval()
    report = s.execute(view)
    assert report.outcome != "succeeded"
    assert s.arm.puts == []
    assert _model(s) == ("gpt-4o", "2024-08-06")


def test_a_disabled_kill_switch_defers_the_apply() -> None:
    s = _stored()
    view = s.executing()
    on = s.call(
        "PUT", DAVE, "/emergency-disable", json={"disabled": True, "reason": "incident_response"}
    )
    assert on.status_code == 200, on.text
    report = s.execute(view)
    assert (report.outcome, report.reason) == ("deferred", "emergency_disabled")
    assert s.arm.puts == []
    assert _model(s) == ("gpt-4o", "2024-08-06")


def test_an_unusable_stored_entry_leaves_the_intent_advisory() -> None:
    s = make_slice(stored_entries=[WriteTargetEntry("foundry", "/subscriptions/not-an-account")])
    assert s.registry.names() == ()
    assert s.advisory is True
