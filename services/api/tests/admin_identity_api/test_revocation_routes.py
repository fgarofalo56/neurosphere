"""PRP-39 item 4: revoke, read and lift a principal's revocation through the composed service."""

from __future__ import annotations

from typing import Any

import pytest
from identity_harness import (  # pyright: ignore[reportMissingImports]
    BASE,
    CUSTOMER,
    DOMAIN_ADMIN,
    TARGET,
    IdentityWorld,
    configure_env,
    pid,
)
from neurosphere_api.runtime.builders import REVOCATION_HOOKS, BuildContext, BuilderSpec
from neurosphere_core.errors import DependencyTransientError

ME = "/api/v1/me/domains"
CHAIN = f"{CUSTOMER}.identity-admin"


class PushCloser:
    def __init__(self) -> None:
        self.closed_for: list[str] = []

    async def close_for_principal(self, principal_id: str) -> int:
        self.closed_for.append(principal_id)
        return 1


@pytest.fixture(autouse=True)
def _auth(monkeypatch: pytest.MonkeyPatch) -> None:
    configure_env(monkeypatch)


@pytest.fixture
def closer() -> PushCloser:
    return PushCloser()


@pytest.fixture
def world(closer: PushCloser) -> IdentityWorld:
    def register(ctx: BuildContext) -> None:
        ctx.shared(REVOCATION_HOOKS).register_push_registry("websocket", closer)

    return IdentityWorld.build(extra_builders=(BuilderSpec("push", (), register),))


def _url(object_id: str) -> str:
    return f"{BASE}/principals/{pid(object_id)}/revocation"


def _body(mode: str, reason: str = "compromised") -> dict[str, Any]:
    return {"schema_version": "1.0.0", "reason": reason, "mode": mode}


def _ops(world: IdentityWorld) -> list[tuple[str, str]]:
    return [(r["kind"], r["operation"]) for r in world.chain(CHAIN)]


def test_issued_before_revocation_denies_old_tokens_and_fans_out(
    world: IdentityWorld, closer: PushCloser
) -> None:
    with world.composed.client() as client:
        old = world.auth(TARGET)
        assert client.get(ME, headers=old).status_code == 200
        response = client.post(
            _url(TARGET), json=_body("issued_before"), headers=world.auth(DOMAIN_ADMIN)
        )
        assert response.status_code == 200, response.text
        status = response.json()
        assert status["revoked"] is True and status["mode"] == "issued_before"
        assert status["propagation_bound_seconds"] == 60
        assert status["revoked_by"] == pid(DOMAIN_ADMIN)
        denied = client.get(ME, headers=old)
        world.clock.advance(61)  # beyond the clock-skew allowance: a fresh sign-in works
        fresh = client.get(ME, headers=world.auth(TARGET))
    assert denied.status_code == 403 and denied.json()["reason"] == "principal_revoked"
    assert fresh.status_code == 200
    assert closer.closed_for == [pid(TARGET)]  # one push close per revoke
    assert _ops(world) == [("before", "principal.revoke"), ("after", "principal.revoke")]
    assert world.chain(CHAIN)[-1]["outcome"]["detail"] == "mode=issued_before"


def test_until_lifted_refuses_new_tokens_until_lifted(
    world: IdentityWorld, closer: PushCloser
) -> None:
    with world.composed.client() as client:
        revoked = client.post(
            _url(TARGET), json=_body("until_lifted"), headers=world.auth(DOMAIN_ADMIN)
        )
        assert revoked.status_code == 200, revoked.text
        world.clock.advance(3600)
        blocked = client.get(ME, headers=world.auth(TARGET))
        status = client.get(_url(TARGET), headers=world.auth(DOMAIN_ADMIN))
        lifted = client.delete(
            _url(TARGET), params={"reason": "cleared"}, headers=world.auth(DOMAIN_ADMIN)
        )
        after_lift = client.get(ME, headers=world.auth(TARGET))
        again = client.delete(_url(TARGET), headers=world.auth(DOMAIN_ADMIN))
    assert blocked.status_code == 403 and blocked.json()["reason"] == "principal_revoked"
    assert status.json()["mode"] == "until_lifted"
    assert lifted.status_code == 200, lifted.text
    assert lifted.json()["mode"] == "issued_before"
    assert after_lift.status_code == 200
    assert again.status_code == 404 and again.json()["reason"] == "no_active_block"
    assert closer.closed_for == [pid(TARGET)]  # a lift closes nothing
    ops = _ops(world)
    assert ops[:4] == [
        ("before", "principal.revoke"),
        ("after", "principal.revoke"),
        ("before", "principal.revoke_lift"),
        ("after", "principal.revoke_lift"),
    ]


def test_status_of_a_principal_never_revoked(world: IdentityWorld) -> None:
    with world.composed.client() as client:
        response = client.get(_url(TARGET), headers=world.auth(DOMAIN_ADMIN))
    assert response.status_code == 200
    assert response.json()["revoked"] is False and response.json()["mode"] is None


def test_cross_scope_target_is_403_and_audited(world: IdentityWorld) -> None:
    other = pid(TARGET).replace(":contoso:", ":fabrikam:")
    with world.composed.client() as client:
        response = client.post(
            f"{BASE}/principals/{other}/revocation",
            json=_body("issued_before"),
            headers=world.auth(DOMAIN_ADMIN),
        )
    assert response.status_code == 403
    assert response.json()["reason"] == "cross_scope_target"
    assert [(r["kind"], r["denial"]["reason"]) for r in world.chain(CHAIN)] == [
        ("denied", "cross_scope_target")
    ]


def test_store_outage_is_503_never_an_allow(world: IdentityWorld) -> None:
    world.revocations.fail_with(
        DependencyTransientError("down", reason="revocation_store_unavailable")
    )
    with world.composed.client() as client:
        post = client.post(
            _url(TARGET), json=_body("until_lifted"), headers=world.auth(DOMAIN_ADMIN)
        )
        get = client.get(_url(TARGET), headers=world.auth(DOMAIN_ADMIN))
        lift = client.delete(_url(TARGET), headers=world.auth(DOMAIN_ADMIN))
    assert post.status_code == 503 and get.status_code == 503 and lift.status_code == 503


def test_analyst_cannot_revoke_or_lift(world: IdentityWorld) -> None:
    with world.composed.client() as client:
        post = client.post(
            _url(DOMAIN_ADMIN), json=_body("until_lifted"), headers=world.auth(TARGET)
        )
        lift = client.delete(_url(DOMAIN_ADMIN), headers=world.auth(TARGET))
    assert post.status_code == 403 and post.json()["reason"] == "permission_missing"
    assert lift.status_code == 403


def test_invalid_mode_or_reason_is_422(world: IdentityWorld) -> None:
    with world.composed.client() as client:
        mode = client.post(_url(TARGET), json=_body("forever"), headers=world.auth(DOMAIN_ADMIN))
        reason = client.post(
            _url(TARGET),
            json=_body("issued_before", reason="Free text"),
            headers=world.auth(DOMAIN_ADMIN),
        )
    assert mode.status_code == 422 and reason.status_code == 422
    assert world.chain(CHAIN) == []
