"""PRP-21 round 2 item 1: admission is charged by ``require`` after the permission check."""

from typing import Annotated, Any

import authz.authz_helpers as helpers  # pyright: ignore[reportMissingImports]
from fastapi import APIRouter, Depends
from neurosphere_api.authz import require
from neurosphere_core.admission import QuotaLimit, QuotaPolicy, TokenBucketLimiter
from neurosphere_core.auth.scope import Permission, Role
from neurosphere_core.scope import IdentityScope

ALICE: str = helpers.ALICE  # finance only
BOB: str = helpers.BOB  # operations only
FINANCE: str = helpers.FINANCE
OPERATIONS: str = helpers.OPERATIONS
HR: str = helpers.HR

POLICIES = (
    helpers.policy(ALICE, helpers.role(Role.VIEWER, FINANCE)),
    helpers.policy(BOB, helpers.role(Role.VIEWER, OPERATIONS)),
)


class _Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def _harness(burst: int = 3, rate: float = 1.0) -> tuple[Any, TokenBucketLimiter, _Clock]:
    h = helpers.harness(*POLICIES)
    clock = _Clock()
    limiter = TokenBucketLimiter(
        QuotaPolicy(default=QuotaLimit(rate_per_second=rate, burst=burst)), clock=clock
    )
    h.app.state.admission = limiter
    return h, limiter, clock


def test_noisy_domain_is_throttled_and_other_domain_still_served() -> None:
    h, _, clock = _harness(burst=3)
    noisy = [h.client.get("/t/data", headers=h.auth(ALICE)) for _ in range(5)]
    assert [r.status_code for r in noisy] == [200, 200, 200, 429, 429]
    body = noisy[3].json()
    assert body["code"] == "rate_limited"
    assert int(noisy[3].headers["retry-after"]) >= 1
    # another domain's principal is unaffected
    assert h.client.get("/t/data", headers=h.auth(BOB)).status_code == 200
    # tokens refill with the fake clock
    clock.now += 5
    assert h.client.get("/t/data", headers=h.auth(ALICE)).status_code == 200


def test_off_by_default_never_throttles() -> None:
    h = helpers.harness(*POLICIES)
    assert not hasattr(h.app.state, "admission")
    assert all(h.client.get("/t/data", headers=h.auth(ALICE)).status_code == 200 for _ in range(50))


def test_no_identity_scope_state_is_required() -> None:
    h, _, _ = _harness()
    # The limiter works from the derived scope alone: nothing sets request.state.identity_scope.
    assert h.client.get("/t/data", headers=h.auth(ALICE)).status_code == 200


def test_denied_request_is_not_charged() -> None:
    h, limiter, _ = _harness(burst=2)
    for _ in range(10):
        r = h.client.get(f"/t/domains/{HR}/data", headers=h.auth(ALICE))
        assert r.status_code == 403
    # the caller's bucket is untouched: two permitted requests still pass
    assert h.client.get(f"/t/domains/{FINANCE}/data", headers=h.auth(ALICE)).status_code == 200
    assert h.client.get(f"/t/domains/{FINANCE}/data", headers=h.auth(ALICE)).status_code == 200
    assert h.client.get(f"/t/domains/{FINANCE}/data", headers=h.auth(ALICE)).status_code == 429
    del limiter


def test_caller_supplied_domain_never_selects_a_bucket() -> None:
    h, _, _ = _harness(burst=2)
    ok = h.client.get("/t/data", headers=h.auth(ALICE))
    assert ok.status_code == 200
    # query string, header and cookie domains are ignored: they all hit the same bucket
    for extra in ({"params": {"domain_id": OPERATIONS}}, {"headers": {"x-domain": OPERATIONS}}):
        headers = {**h.auth(ALICE), **extra.get("headers", {})}
        r = h.client.get("/t/data", headers=headers, params=extra.get("params"))
        assert r.status_code in (200, 429)
    assert h.client.get("/t/data", headers=h.auth(ALICE)).status_code == 429
    assert h.client.get("/t/data", headers=h.auth(BOB)).status_code == 200


def test_one_charge_per_request_with_several_requires() -> None:
    router = APIRouter()

    @router.get("/twice")
    async def twice(
        a: Annotated[IdentityScope, Depends(require(Permission.DATA_READ))],
        b: Annotated[IdentityScope, Depends(require(Permission.DATA_READ))],
    ) -> dict[str, str]:
        return {"ok": (a.scope_hash == b.scope_hash and "yes") or "no"}

    h = helpers.harness(*POLICIES, routers={"/t": router})
    h.app.state.admission = TokenBucketLimiter(
        QuotaPolicy(default=QuotaLimit(rate_per_second=1.0, burst=2)), clock=_Clock()
    )
    assert h.client.get("/t/twice", headers=h.auth(ALICE)).status_code == 200
    assert h.client.get("/t/twice", headers=h.auth(ALICE)).status_code == 200
    assert h.client.get("/t/twice", headers=h.auth(ALICE)).status_code == 429
