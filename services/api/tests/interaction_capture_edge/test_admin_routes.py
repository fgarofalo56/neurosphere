"""PRP-103 item 5: the read-only capture admin routes (acceptance criterion 9).

Composes the real authz builder and a stub capture builder (see ``admin_helpers``). Checks: 200
with metadata only, 404 for an unknown policy, the not-configured view, domain filtering, and
that no response carries a canary from content that went through a real capture.
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any

import pytest
from authz.authz_helpers import FINANCE, OPERATIONS  # pyright: ignore[reportMissingImports]
from runtime_api.runtime_helpers import configure_auth_env  # pyright: ignore[reportMissingImports]

from . import edge_helpers as h
from .admin_helpers import (
    CUSTOMER_ADMIN,
    FIN_ADMIN,
    OPS_ADMIN,
    POLICIES,
    STATUS,
    build_world,
    contoso_policy,
)

_PREFIXES = ("NS_AUTH_", "NS_STORE_", "NS_CORS_", "NS_COSMOS_", "NS_REVOCATION_", "NS_COPILOT_")
_NAMES = ("NS_CLOUD", "NS_INGEST_PRODUCERS_FILE", "NS_SCAN_ENABLED", "NS_MCP_RESOURCE_SERVER_URL")

#: Every key a policy view may carry: metadata only.
POLICY_KEYS = {
    "policy_id",
    "display_name",
    "version",
    "previous_version",
    "domain_id",
    "source_ids",
    "parts",
    "detector_set_version",
    "customer_dictionary_ids",
    "redaction_mode",
    "kept_categories",
    "sampling",
    "max_part_chars",
    "retention_class",
    "retention_days",
    "state",
    "approved_intent_id",
    "approved_audit_id",
    "effective_from",
}
#: Never a key anywhere in a response.
FORBIDDEN = ("prompt", "response", "messages", "content", "body", "kek", "connection", "secret")


@pytest.fixture(autouse=True)
def _env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in sorted(os.environ):
        if name.startswith(_PREFIXES) or name in _NAMES:
            monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("NS_ENV", "local")
    configure_auth_env(monkeypatch)


def _keys(value: Any) -> set[str]:
    out: set[str] = set()
    stack = [value]
    while stack:
        item = stack.pop()
        if isinstance(item, dict):
            for k, v in item.items():  # pyright: ignore[reportUnknownVariableType]
                out.add(str(k))  # pyright: ignore[reportUnknownArgumentType]
                stack.append(v)
        elif isinstance(item, list):
            stack.extend(item)  # pyright: ignore[reportUnknownArgumentType]
    return out


def _assert_metadata_only(body: Any) -> None:
    for key in _keys(body):
        lowered = key.lower()
        assert not any(word in lowered for word in FORBIDDEN), key


def _two_domains() -> list[dict[str, Any]]:
    return [
        contoso_policy("fin-capture"),
        contoso_policy("ops-capture", OPERATIONS, state="proposed", approved_audit_id=None),
    ]


def test_list_returns_every_policy_metadata_only_for_a_customer_admin() -> None:
    world = build_world(policies=_two_domains())
    response = world.get(POLICIES, CUSTOMER_ADMIN)
    assert response.status_code == 200, response.text
    assert response.headers["Cache-Control"] == "no-store"
    body = response.json()
    assert body["configured"] is True
    assert body["reason"] is None
    assert body["truncated"] is False
    assert [p["policy_id"] for p in body["items"]] == ["fin-capture", "ops-capture"]
    fin = body["items"][0]
    assert set(fin) == POLICY_KEYS
    assert fin["domain_id"] == FINANCE
    assert fin["source_ids"] == [h.SOURCE]
    assert fin["parts"] == ["prompt", "response"]
    assert fin["sampling"] == {"rate": 1.0, "max_per_minute": 600}
    assert fin["state"] == "active"
    assert fin["approved_audit_id"] == h.policy_doc()["approved_audit_id"]
    assert body["items"][1]["approved_audit_id"] is None
    # The parts list holds part names as values; no KEY of the response names content.
    _assert_metadata_only({k: v for k, v in body.items() if k != "items"})
    for item in body["items"]:
        _assert_metadata_only({k: v for k, v in item.items() if k != "parts"})


def test_domain_filter_returns_only_that_domain() -> None:
    world = build_world(policies=_two_domains())
    response = world.get(POLICIES, FIN_ADMIN, domain_id=FINANCE)
    assert response.status_code == 200, response.text
    assert [p["policy_id"] for p in response.json()["items"]] == ["fin-capture"]
    # A customer admin may name any domain of its customer.
    response = world.get(POLICIES, CUSTOMER_ADMIN, domain_id=OPERATIONS)
    assert [p["policy_id"] for p in response.json()["items"]] == ["ops-capture"]


def test_limit_truncates_the_page() -> None:
    world = build_world(policies=_two_domains())
    body = world.get(POLICIES, CUSTOMER_ADMIN, limit=1).json()
    assert len(body["items"]) == 1
    assert body["truncated"] is True


def test_detail_returns_one_policy() -> None:
    world = build_world(policies=_two_domains())
    response = world.get(f"{POLICIES}/fin-capture", FIN_ADMIN)
    assert response.status_code == 200, response.text
    assert set(response.json()) == POLICY_KEYS
    assert response.json()["version"] == h.POLICY_VERSION


def test_unknown_policy_is_404() -> None:
    world = build_world(policies=_two_domains())
    response = world.get(f"{POLICIES}/no-such-policy", CUSTOMER_ADMIN)
    assert response.status_code == 404
    assert response.json()["reason"] == "capture_policy_not_found"


def test_a_policy_of_another_domain_is_404_like_an_unknown_one() -> None:
    world = build_world(policies=_two_domains())
    hidden = world.get(f"{POLICIES}/fin-capture", OPS_ADMIN)
    unknown = world.get(f"{POLICIES}/no-such-policy", OPS_ADMIN)
    assert hidden.status_code == unknown.status_code == 404
    assert hidden.json()["reason"] == unknown.json()["reason"] == "capture_policy_not_found"


def test_not_configured_is_an_empty_off_view_not_a_500() -> None:
    world = build_world(configured=False)
    listed = world.get(POLICIES, CUSTOMER_ADMIN)
    assert listed.status_code == 200, listed.text
    assert listed.json() == {
        "items": [],
        "truncated": False,
        "configured": False,
        "reason": "capture_not_configured",
    }
    status = world.get(STATUS, CUSTOMER_ADMIN)
    assert status.status_code == 200, status.text
    body = status.json()
    assert body["state"] == "off"
    assert body["off_reason"] == "capture_not_configured"
    assert body["configured"] is False
    assert body["counters"] is None
    assert body["policies"]["total"] == 0
    detail = world.get(f"{POLICIES}/fin-capture", CUSTOMER_ADMIN)
    assert detail.status_code == 404
    assert detail.json()["reason"] == "capture_not_configured"


def test_status_reports_the_off_reason_and_policy_counts() -> None:
    world = build_world(policies=_two_domains(), off_reason="setting_off")
    body = world.get(STATUS, CUSTOMER_ADMIN).json()
    assert body["state"] == "off"
    assert body["off_reason"] == "setting_off"
    assert body["configured"] is True
    assert body["policies"] == {
        "total": 2,
        "proposed": 1,
        "active": 1,
        "suspended": 0,
        "retired": 0,
    }
    # The edge was never built (setting off): no counters.
    assert body["counters"] is None


def test_a_domain_scoped_status_has_no_deployment_wide_counters() -> None:
    class Stats:
        def snapshot(self) -> dict[str, Any]:
            return {"captured": 5}

    world = build_world(policies=_two_domains(), off_reason=None, edge=object(), stats=Stats())
    body = world.get(STATUS, FIN_ADMIN, domain_id=FINANCE).json()
    assert body["domain_id"] == FINANCE
    assert body["policies"]["total"] == 1
    assert body["counters"] is None
    wide = world.get(STATUS, CUSTOMER_ADMIN).json()
    assert wide["counters"]["captured"] == 5


def test_counter_keys_that_are_not_reason_codes_are_dropped() -> None:
    mark = "NSCANARY-" + "q" * 12

    class Stats:
        def snapshot(self) -> dict[str, Any]:
            return {
                "captured": 2,
                "capture_failed": {"key_wrap_failed": 1, mark: 3},
                "prompt": mark,
                "capture_shed": True,  # not an integer counter
            }

    world = build_world(off_reason="no_policy", edge=object(), stats=Stats())
    response = world.get(STATUS, CUSTOMER_ADMIN)
    assert mark not in response.text
    counters = response.json()["counters"]
    assert counters["captured"] == 2
    assert counters["capture_failed"] == {"key_wrap_failed": 1}
    assert counters["capture_shed"] == 0


def test_no_response_carries_captured_content(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A real capture runs first; its counters are served, its canaries never are."""
    h.ISSUED.clear()
    mark = h.canary()
    other = h.canary()

    async def capture_one() -> h.Rig:
        r = await h.rig(tmp_path, monkeypatch)
        data = h.telemetry_data(
            "evt-admin-1", domain_id=h.DOMAIN, prompt=f"hello {mark}", response=f"ok {other}"
        )
        body = json.dumps(h.ce(h.TELEMETRY_TYPE, data)).encode()
        await r.service.ingest_events(r.producer, body, h.STRUCTURED, correlation_id="req-admin")
        return r

    r = asyncio.run(capture_one())
    assert r.capture is not None
    assert r.capture.stats.captured == 1
    world = build_world(
        policies=_two_domains(), off_reason=None, edge=r.capture, stats=r.capture.stats
    )
    texts: list[str] = []
    for path, params in (
        (POLICIES, {}),
        (f"{POLICIES}/fin-capture", {}),
        (STATUS, {}),
        (STATUS, {"domain_id": FINANCE}),
    ):
        response = world.get(path, CUSTOMER_ADMIN, **params)
        assert response.status_code == 200, response.text
        texts.append(response.text)
    status = json.loads(texts[2])
    assert status["state"] == "active"
    assert status["off_reason"] is None
    assert status["counters"]["captured"] == 1
    _assert_metadata_only(status)
    joined = "\n".join(texts)
    for value in h.ISSUED:
        assert value not in joined
    assert "NSCANARY-" not in joined
