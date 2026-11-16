"""PRP-59 item 1: the plan route refuses a body-supplied scan (#36)."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from authz.authz_helpers import Harness  # pyright: ignore[reportMissingImports]
from neurosphere_api.deploy.plan import build_router as plan_router
from neurosphere_api.deploy.scan import ScanService, ScanSettings, configure_scan
from neurosphere_api.deploy.scan import build_router as scan_router

from .conftest import ADMIN
from .test_plan import COMMERCIAL, KV, _matrix, _scan  # pyright: ignore[reportPrivateUsage]
from .test_scan import ROWS, SUB_A, SUB_B, FakeReader, _consent  # pyright: ignore[reportPrivateUsage]

PROFILE = COMMERCIAL.model_copy(update={"regions": ("eastus",)})


def _mounted(mount: Callable[[dict[str, Any]], Harness]) -> Harness:
    h = mount({"/v1/deploy/scan": scan_router(), "/v1/deploy/plan": plan_router(_matrix())})
    configure_scan(
        h.app, ScanService(FakeReader({SUB_A, SUB_B}, ROWS), ScanSettings(result_ttl_seconds=900.0))
    )
    return h


def _post_scan(h: Harness) -> dict[str, Any]:
    body = {"subscription_ids": [SUB_A], "consent": _consent(SUB_A)}
    r = h.client.post("/v1/deploy/scan", json=body, headers=h.auth(ADMIN))
    assert r.status_code == 200, r.text
    out: dict[str, Any] = r.json()
    return out


def test_body_scan_is_refused_before_planning(mount: Callable[[dict[str, Any]], Harness]) -> None:
    h = _mounted(mount)
    r = h.client.post(
        "/v1/deploy/plan",
        json={
            "profile": PROFILE.model_dump(mode="json"),
            "scan": _scan(KV).model_dump(mode="json"),
        },
        headers=h.auth(ADMIN),
    )
    assert r.status_code == 422, r.text
    assert r.json()["reason"] == "scan_body_not_accepted"


def test_body_scan_is_refused_even_with_a_valid_scan_id(
    mount: Callable[[dict[str, Any]], Harness],
) -> None:
    h = _mounted(mount)
    scan = _post_scan(h)
    r = h.client.post(
        "/v1/deploy/plan",
        json={
            "profile": PROFILE.model_dump(mode="json"),
            "scan_id": scan["scan_id"],
            "scan": _scan(KV).model_dump(mode="json"),
        },
        headers=h.auth(ADMIN),
    )
    assert (r.status_code, r.json()["reason"]) == (422, "scan_body_not_accepted")


def test_scan_id_still_plans(mount: Callable[[dict[str, Any]], Harness]) -> None:
    h = _mounted(mount)
    scan = _post_scan(h)
    r = h.client.post(
        "/v1/deploy/plan",
        json={"profile": PROFILE.model_dump(mode="json"), "scan_id": scan["scan_id"]},
        headers=h.auth(ADMIN),
    )
    assert r.status_code == 200, r.text
