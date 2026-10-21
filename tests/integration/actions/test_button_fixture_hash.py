"""PRP-17 item 7b: the UI's button request and the REST request confirm to ONE hash.

``frontend/src/features/actions/__fixtures__/button-intent-request.json`` is the exact body the
button flow's builder sends (``channel: "button"``). It is drafted through the REAL app (item 7a's
in-process slice), next to a REST body that differs only in ``channel`` and ``idempotency_key``.
Both are validated and presented under the slice's frozen clock; the server-issued
``confirmation_hash`` must be identical (channel and idempotency key are not hashed) while the
intents stay distinct. The fixture is loaded unchanged: the slice's fake ARM is taught the
fixture's deployment instead.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any, Final

import httpx
from neurosphere_core.actions import compute_confirmation_hash

from .support import FAKES, TARGET_VERSION, make_slice

_FIXTURE: Final = (
    Path(__file__).resolve().parents[3]
    / "frontend"
    / "src"
    / "features"
    / "actions"
    / "__fixtures__"
    / "button-intent-request.json"
)
_FIXTURE_DEPLOYMENT: Final = "support-gpt"
_FIXTURE_MODEL: Final = ("gpt-4.1-mini", "2026-04-14")


class FixtureArm(FAKES.FakeArm):  # type: ignore[misc, name-defined]
    """The slice's fake ARM, serving the fixture's deployment (``support-gpt``) at its ETag."""

    def _handle(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path.replace(f"/deployments/{_FIXTURE_DEPLOYMENT}", "/deployments/dep1")
        return super()._handle(
            httpx.Request(request.method, request.url.copy_with(path=path), content=request.content)
        )


def _button_body() -> dict[str, Any]:
    body = json.loads(_FIXTURE.read_text(encoding="utf-8"))
    assert body["channel"] == "button"
    return body


def test_button_and_rest_drafts_of_the_same_change_share_one_confirmation_hash() -> None:
    button = _button_body()
    rest = copy.deepcopy(button)
    rest["channel"] = "rest"
    rest["idempotency_key"] = "rest-swap-0002-same-change"
    assert {k: v for k, v in button.items() if k not in {"channel", "idempotency_key"}} == {
        k: v for k, v in rest.items() if k not in {"channel", "idempotency_key"}
    }

    arm = FixtureArm(
        FAKES.deployment(etag=button["target_version"]),
        models=[*FAKES.DEFAULT_MODELS, FAKES.model_entry(*_FIXTURE_MODEL)],
        put_state="Succeeded",
    )
    assert button["target_version"] != TARGET_VERSION  # the fixture's own ETag, not the slice's
    s = make_slice(arm=arm)

    presented = [s.presented(body) for body in (button, rest)]

    button_intent, rest_intent = (view["intent"] for view in presented)
    assert button_intent["channel"] == "button" and rest_intent["channel"] == "rest"
    assert button_intent["intent_id"] != rest_intent["intent_id"]
    assert button_intent["idempotency_key"] != rest_intent["idempotency_key"]
    assert button_intent["state"] == rest_intent["state"] == "awaiting_confirmation"
    assert button_intent["confirmation_expires_at"] == rest_intent["confirmation_expires_at"]
    assert button_intent["confirmation_hash"] is not None
    assert button_intent["confirmation_hash"] == rest_intent["confirmation_hash"]
    # Not just equal to each other: the value is the canonical hash of the confirmed change.
    assert button_intent["confirmation_hash"] == compute_confirmation_hash(button_intent)
    # Presenting a confirmation only ever READS the target.
    assert arm.puts == []
