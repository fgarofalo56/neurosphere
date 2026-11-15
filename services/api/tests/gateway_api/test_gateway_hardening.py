"""PRP-46 (#148): optional inventory lists degrade on 403; _record_failure logs, never raises."""

from __future__ import annotations

import logging
from typing import Any

import httpx
import pytest
from gateway_harness import (  # pyright: ignore[reportMissingImports]
    ADMIN,
    FINANCE,
    PREFIX,
    RID,
    FakeArm,
    make_env,
)
from neurosphere_core.gateway import inventory as inv


def _sync_path(gateway_id: str) -> str:
    return f"/domains/{FINANCE}/gateways/{gateway_id}/sync"


class _ForbiddenBackendsArm(FakeArm):  # type: ignore[misc,valid-type]
    def handle(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path.lower()
        if path in (f"{RID.lower()}/backends", f"{RID.lower()}/policyfragments"):
            self.requests.append(request)
            return httpx.Response(403, json={})
        return super().handle(request)


def test_403_on_optional_lists_degrades_instead_of_failing() -> None:
    env = make_env(_ForbiddenBackendsArm())
    created = env.register().json()
    synced = env.call("POST", ADMIN, _sync_path(created["id"]))
    assert synced.status_code == 200, synced.text
    body = synced.json()
    assert body["last_sync_status"] == "ok"
    assert body["capabilities"]["backends"] == "unreadable"
    assert body["capabilities"]["policy_fragments"] == "unreadable"
    assert body["inventory_counts"]["backends"] == 0
    assert body["inventory_counts"]["apis"] == 2


def test_record_failure_logs_type_and_never_raises(
    caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    arm = FakeArm()
    env = make_env(arm)
    created = env.register().json()
    arm.throttle_forever = True

    async def no_sleep(_: float) -> None:
        return None

    monkeypatch.setattr(inv, "_sleep", no_sleep)

    async def boom(*_a: Any, **_k: Any) -> Any:
        raise RuntimeError("store down")

    monkeypatch.setattr(env.store, "replace", boom)
    with caplog.at_level(logging.WARNING, logger="neurosphere.api.gateway"):
        resp = env.call("POST", ADMIN, _sync_path(created["id"]))
    assert resp.status_code == 503
    record = next(r for r in caplog.records if r.name == "neurosphere.api.gateway")
    assert record.error == "RuntimeError"  # type: ignore[attr-defined]
    assert record.gateway_id == created["id"]  # type: ignore[attr-defined]
    assert PREFIX
