"""PRP-08 item 11: tag-trusted consent (#35), audit events (#37), scan ids (#36)."""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from authz.authz_helpers import Harness  # pyright: ignore[reportMissingImports]
from neurosphere_api.deploy.plan import PlanRequest, build_plan
from neurosphere_api.deploy.plan import build_router as plan_router
from neurosphere_api.deploy.plan.router import validate_body_scan
from neurosphere_api.deploy.scan import (
    ScanService,
    ScanSettings,
    configure_scan,
)
from neurosphere_api.deploy.scan import (
    build_router as scan_router,
)
from neurosphere_api.deploy.scan.audit import audit_chain
from neurosphere_core.audit import AuditRepository
from neurosphere_core.errors import InvalidSchemaError

from .conftest import ADMIN, VIEWER
from .test_plan import COMMERCIAL, KV, _matrix, _res, _scan  # pyright: ignore[reportPrivateUsage]
from .test_scan import ROWS, SUB_A, SUB_B, FakeReader, _consent  # pyright: ignore[reportPrivateUsage]

NOW = datetime(2026, 10, 16, 12, 0, 0, tzinfo=UTC)
#: Fake scan rows live in eastus; residency needs the profile region to match.
PROFILE = COMMERCIAL.model_copy(update={"regions": ("eastus",)})
SECRETISH = ("owner@example.com", "Bearer", "password", "fake-token", "eyJ")


class Clock:
    def __init__(self) -> None:
        self.now = NOW

    def __call__(self) -> datetime:
        return self.now


# ------------------------------------------------------------------ #35 tags are not consent


@pytest.mark.parametrize(
    "tags",
    [
        {"neurosphere:owner-consent": "granted"},
        {"consent": "true", "owner-consent-id": "consent-1"},
        {"neurosphere:created-by": "neurosphere", "neurosphere:consent": "granted"},
    ],
)
def test_consent_looking_tag_without_recorded_consent_is_needs_consent(
    tags: dict[str, str],
) -> None:
    res = _res("key_vault", "Microsoft.KeyVault/vaults", "kv-tagged", tags=tags)
    plan = build_plan(PlanRequest(profile=COMMERCIAL, scan=_scan(res)), matrix=_matrix(), now=NOW)
    item = next(i for i in plan.items if i.service == "key_vault")
    assert item.status == "needs_consent"
    assert not any(i.status == "reuse" for i in plan.items)
    assert plan.consents == []


# ------------------------------------------------------------------ harness


def _mounted(
    mount: Callable[[dict[str, Any]], Harness], clock: Clock | None = None, ttl: float = 900.0
) -> tuple[Harness, AuditRepository]:
    h = mount({"/v1/deploy/scan": scan_router(), "/v1/deploy/plan": plan_router(_matrix())})
    service = ScanService(
        FakeReader({SUB_A, SUB_B}, ROWS),
        ScanSettings(result_ttl_seconds=ttl),
        clock=clock or Clock(),
    )
    configure_scan(h.app, service)
    repo = h.app.state.audit_repository
    assert isinstance(repo, AuditRepository)
    return h, repo


async def _events(h: Harness, repo: AuditRepository) -> list[Any]:
    chain = audit_chain("contoso")
    del h
    return await repo.read_range(chain)  # type: ignore[no-any-return]


def _scan_body() -> dict[str, Any]:
    return {"consent": _consent(SUB_A), "subscription_ids": [SUB_A]}


def _post_scan(h: Harness, who: Any = ADMIN) -> dict[str, Any]:
    r = h.client.post("/v1/deploy/scan", json=_scan_body(), headers=h.auth(who))
    assert r.status_code == 200, r.text
    return r.json()


# ------------------------------------------------------------------ #36 scan ids


def test_scan_returns_scan_id_and_plan_consumes_it(
    mount: Callable[[dict[str, Any]], Harness],
) -> None:
    h, _ = _mounted(mount)
    scan = _post_scan(h)
    assert scan["scan_id"].startswith("scan-")
    r = h.client.post(
        "/v1/deploy/plan",
        json={"profile": PROFILE.model_dump(mode="json"), "scan_id": scan["scan_id"]},
        headers=h.auth(ADMIN),
    )
    assert r.status_code == 200, r.text
    kv = next(i for i in r.json()["plan"]["items"] if i["service"] == "key_vault")
    assert kv["status"] == "needs_consent"  # discovered via the stored scan, no consent recorded


def test_scan_id_wins_over_body_scan(mount: Callable[[dict[str, Any]], Harness]) -> None:
    h, _ = _mounted(mount)
    scan = _post_scan(h)
    body = {
        "profile": PROFILE.model_dump(mode="json"),
        "scan_id": scan["scan_id"],
        "scan": _scan(KV).model_dump(mode="json"),  # different content, must be ignored
    }
    r = h.client.post("/v1/deploy/plan", json=body, headers=h.auth(ADMIN))
    assert r.status_code == 200, r.text
    kv = next(i for i in r.json()["plan"]["items"] if i["service"] == "key_vault")
    assert kv["existing_resource_id"].endswith("/kv-a")


def test_foreign_scan_id_is_forbidden(mount: Callable[[dict[str, Any]], Harness]) -> None:
    h, _ = _mounted(mount)
    scan = _post_scan(h, ADMIN)
    # VIEWER lacks config.manage, so grant a second admin-like principal: reuse the store directly.
    service = h.app.state.scan_service
    assert isinstance(service, ScanService)
    other = _other_scope(h)
    with pytest.raises(Exception) as err:
        service.stored_scan(other, scan["scan_id"])
    assert getattr(err.value, "code", None) == "forbidden"
    assert getattr(err.value, "reason", None) == "scan_not_owned"


def _other_scope(h: Harness) -> Any:
    """A verified scope for a different principal (the viewer), via the real deriver path."""
    captured: dict[str, Any] = {}

    from fastapi import APIRouter, Depends
    from neurosphere_api.authz import require
    from neurosphere_core.auth.scope import Permission

    router = APIRouter()

    @router.get("/whoami")
    async def whoami(scope: Any = Depends(require(Permission.DATA_READ))) -> dict[str, str]:  # noqa: B008
        captured["scope"] = scope
        return {}

    h.app.include_router(router, prefix="/v1/deploy")
    assert h.client.get("/v1/deploy/whoami", headers=h.auth(VIEWER)).status_code == 200
    return captured["scope"]


def test_unknown_and_expired_scan_ids_are_typed(
    mount: Callable[[dict[str, Any]], Harness],
) -> None:
    clock = Clock()
    h, _ = _mounted(mount, clock, ttl=60)
    scan = _post_scan(h)
    profile = PROFILE.model_dump(mode="json")
    unknown = h.client.post(
        "/v1/deploy/plan",
        json={"profile": profile, "scan_id": "scan-" + "0" * 32},
        headers=h.auth(ADMIN),
    )
    assert (unknown.status_code, unknown.json()["reason"]) == (422, "scan_not_found")
    bad = h.client.post(
        "/v1/deploy/plan", json={"profile": profile, "scan_id": "nope"}, headers=h.auth(ADMIN)
    )
    assert bad.status_code == 422
    clock.now = NOW + timedelta(seconds=61)
    expired = h.client.post(
        "/v1/deploy/plan",
        json={"profile": profile, "scan_id": scan["scan_id"]},
        headers=h.auth(ADMIN),
    )
    assert (expired.status_code, expired.json()["reason"]) == (422, "scan_expired")


def test_body_scan_fallback_works_and_is_validated(
    mount: Callable[[dict[str, Any]], Harness],
) -> None:
    h, _ = _mounted(mount)
    profile = PROFILE.model_dump(mode="json")
    ok = h.client.post(
        "/v1/deploy/plan",
        json={"profile": profile, "scan": _scan(KV).model_dump(mode="json")},
        headers=h.auth(ADMIN),
    )
    assert ok.status_code == 200, ok.text
    # Inconsistent: resource listed under a different subscription entry.
    bad_scan = _scan(KV).model_dump(mode="json")
    bad_scan["subscriptions"][0]["subscription_id"] = SUB_B
    bad = h.client.post(
        "/v1/deploy/plan", json={"profile": profile, "scan": bad_scan}, headers=h.auth(ADMIN)
    )
    assert (bad.status_code, bad.json()["reason"]) == (422, "scan_inconsistent")
    not_visible = _scan(KV).model_dump(mode="json")
    not_visible["subscriptions"][0]["status"] = "not_visible"
    with pytest.raises(InvalidSchemaError):
        validate_body_scan(_scan(KV).model_copy(deep=True).__class__.model_validate(not_visible))


# ------------------------------------------------------------------ #37 audit events


async def test_scan_plan_and_consent_each_emit_an_audit_event(
    mount: Callable[[dict[str, Any]], Harness],
) -> None:
    h, repo = _mounted(mount)
    scan = _post_scan(h)
    after_scan = await _events(h, repo)
    ops = [e.operation for e in after_scan]
    assert ops.count("deploy.scan") == 1
    assert ops.count("deploy.consent") == 1  # the scan consent decision
    owner_consent = {
        "consent_id": "consent-owner-1",
        "granted": True,
        "owner_principal": "owner:platform-team",
        "resource_ids": [KV.id],
        "recorded_at": NOW.isoformat(),
    }
    r = h.client.post(
        "/v1/deploy/plan",
        json={
            "profile": PROFILE.model_dump(mode="json"),
            "scan_id": scan["scan_id"],
            "consents": [owner_consent],
        },
        headers=h.auth(ADMIN),
    )
    assert r.status_code == 200, r.text
    events = await _events(h, repo)
    by_op: dict[str, list[Any]] = {}
    for e in events:
        by_op.setdefault(e.operation, []).append(e)
    assert len(by_op["deploy.scan"]) == 1
    assert len(by_op["deploy.plan"]) == 1
    assert len(by_op["deploy.plan.consent"]) == 1
    plan_event = by_op["deploy.plan"][0]
    assert plan_event.outcome.detail == "scan_source=store"
    assert plan_event.subject.target.entity_type == "deployment_plan"
    assert plan_event.channel == "rest"
    assert plan_event.actor.principal_pseudonym
    assert plan_event.scope_hash
    scan_event = by_op["deploy.scan"][0]
    assert scan_event.subject.target.canonical_id.endswith(scan["scan_id"])
    blob = json.dumps([e.model_dump(mode="json") for e in events])
    for needle in SECRETISH:
        assert needle not in blob
    # Raw subscription and consent ids never appear in an event (digests only).
    assert SUB_A not in blob
    assert "consent-owner-1" not in blob


async def test_refused_scan_is_audited_as_denied(
    mount: Callable[[dict[str, Any]], Harness],
) -> None:
    h, repo = _mounted(mount)
    r = h.client.post("/v1/deploy/scan", json={"subscription_ids": [SUB_A]}, headers=h.auth(ADMIN))
    assert r.status_code == 403
    events = await _events(h, repo)
    assert [(e.kind, e.operation) for e in events] == [("denied", "deploy.scan")]
    assert events[0].denial.reason == "consent_missing"


def test_audit_not_configured_fails_closed(mount: Callable[[dict[str, Any]], Harness]) -> None:
    h, _ = _mounted(mount)
    h.app.state.audit_repository = None
    r = h.client.post("/v1/deploy/scan", json=_scan_body(), headers=h.auth(ADMIN))
    assert r.status_code == 503
    assert r.json()["reason"] == "audit_not_configured"
    p = h.client.post(
        "/v1/deploy/plan",
        json={"profile": PROFILE.model_dump(mode="json")},
        headers=h.auth(ADMIN),
    )
    assert p.status_code == 503
