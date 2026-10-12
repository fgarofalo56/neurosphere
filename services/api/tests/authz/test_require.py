"""``current_scope`` / ``require``: 401 on bad tokens, 403 with taxonomy body and reason code on
insufficient scope, allow only on an explicit scoped permission, and scope immune to request input.
"""

from __future__ import annotations

from typing import Annotated, Any

import pytest
from fastapi import APIRouter, Depends, Request
from neurosphere_api.authz import AuthzTarget, configure_authz, current_scope, require
from neurosphere_core.auth.jwt import DevIssuer, VerifiedClaims
from neurosphere_core.auth.scope import Permission, Role, ScopeDerivation, ScopeDeriver
from neurosphere_core.cloud import Settings
from neurosphere_core.errors import InvalidSchemaError
from neurosphere_core.scope import IdentityScope

from .authz_helpers import (
    AGENT,
    ALICE,
    AUDIENCE,
    BOB,
    CAROL,
    FINANCE,
    GOV_FINANCE,
    HR,
    NOBODY,
    OPERATIONS,
    OTHER_AGENT,
    OTHER_CUSTOMER_FINANCE,
    TENANT,
    Harness,
    build_router,
    grant,
    harness,
    policy,
    role,
)

POLICIES = (
    policy(ALICE, role(Role.VIEWER, FINANCE), grants=(grant(AGENT, "read"),)),
    policy(BOB, role(Role.ADMIN, FINANCE)),
    policy(CAROL, role(Role.SECURITY_AUDITOR, FINANCE)),
)


@pytest.fixture
def h() -> Harness:
    return harness(*POLICIES)


def _problem(body: dict[str, Any], status: int, code: str, reason: str | None) -> None:
    assert body["status"] == status
    assert body["code"] == code
    assert body["correlation_id"]
    if reason is not None:
        assert body["reason"] == reason


# (principal, method, path, expected status, expected reason). ``None`` principal = no header;
# a string starting with "raw:" is sent verbatim as the Authorization header.
CASES: list[tuple[str | None, str, str, int, str | None]] = [
    (None, "GET", "/t/data", 401, "missing_token"),
    ("raw:Bearer not-a-jwt", "GET", "/t/data", 401, "malformed_token"),
    ("raw:Basic dXNlcjpwYXNz", "GET", "/t/data", 401, "invalid_scheme"),
    (ALICE, "GET", "/t/data", 200, None),
    (ALICE, "GET", f"/t/domains/{FINANCE}/data", 200, None),
    (ALICE, "GET", f"/t/domains/{HR}/data", 403, "target_out_of_scope"),
    (ALICE, "GET", f"/t/domains/{OPERATIONS}/data", 403, "target_out_of_scope"),
    (ALICE, "GET", f"/t/domains/{OTHER_CUSTOMER_FINANCE}/data", 403, "target_out_of_scope"),
    (ALICE, "GET", f"/t/domains/{GOV_FINANCE}/data", 403, "target_out_of_scope"),
    (ALICE, "GET", f"/t/resources/{AGENT}", 200, None),
    (ALICE, "GET", f"/t/resources/{OTHER_AGENT}", 403, "target_out_of_scope"),
    (ALICE, "POST", "/t/config", 403, "permission_missing"),
    (BOB, "POST", "/t/config", 200, None),
    (BOB, "GET", f"/t/domains/{FINANCE}/data", 200, None),
    (BOB, "GET", f"/t/domains/{OPERATIONS}/data", 403, "target_out_of_scope"),
    (BOB, "GET", f"/t/resources/{AGENT}", 403, "target_out_of_scope"),
    (CAROL, "GET", "/t/data", 403, "permission_missing"),
    (CAROL, "GET", f"/t/domains/{FINANCE}/data", 403, "target_out_of_scope"),
    (CAROL, "POST", "/t/config", 403, "permission_missing"),
    (NOBODY, "GET", "/t/data", 403, "permission_missing"),
    (NOBODY, "GET", f"/t/domains/{FINANCE}/data", 403, "target_out_of_scope"),
]


@pytest.mark.parametrize(("who", "method", "path", "status", "reason"), CASES)
def test_require_decision_table(
    h: Harness, who: str | None, method: str, path: str, status: int, reason: str | None
) -> None:
    headers: dict[str, str] = {}
    if who is not None and who.startswith("raw:"):
        headers["Authorization"] = who.removeprefix("raw:")
    elif who is not None:
        headers = h.auth(who)
    response = h.client.request(method, path, headers=headers)
    assert response.status_code == status, response.text
    if status == 200:
        assert response.json()["customer_id"] == "contoso"
        return
    assert response.headers["content-type"].startswith("application/problem+json")
    code = "unauthorized" if status == 401 else "forbidden"
    _problem(response.json(), status, code, reason)


def test_two_authorization_headers_are_rejected(h: Harness) -> None:
    token = h.token(ALICE)
    response = h.client.get(
        "/t/data", headers=[("authorization", f"Bearer {token}"), ("authorization", "Bearer x.y.z")]
    )
    assert response.status_code == 401
    _problem(response.json(), 401, "unauthorized", "ambiguous_token")


def test_token_from_an_untrusted_dev_issuer_is_rejected(h: Harness) -> None:
    rogue = DevIssuer(Settings(env="local"), tenant_id=TENANT, kid="rogue-kid")
    token = rogue.mint(audience=AUDIENCE, object_id=ALICE, now=h.clock.now)
    response = h.client.get("/t/data", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 401
    assert response.json()["code"] == "unauthorized"


def test_expired_token_is_rejected(h: Harness) -> None:
    headers = h.auth(ALICE)
    h.clock.advance(3601)
    response = h.client.get("/t/data", headers=headers)
    assert response.status_code == 401


FORGERIES: list[dict[str, Any]] = [
    {"headers": {"X-NS-Domain-Id": HR, "X-Customer-Id": "fabrikam", "X-NS-Scope": "admin"}},
    {"params": {"domain_id": HR, "customer_id": "fabrikam", "role": "admin"}},
    {"cookies": {"domain_id": HR, "ns_scope": "admin", "customer_id": "fabrikam"}},
    {"json": {"domain_id": HR, "customer_id": "fabrikam", "scope": {"allowed_domains": [HR]}}},
    {"headers": {"X-Forwarded-User": BOB, "X-MS-CLIENT-PRINCIPAL-ID": BOB}},
]


@pytest.mark.parametrize("forgery", FORGERIES, ids=["headers", "query", "cookies", "body", "ids"])
def test_scope_ignores_forged_request_inputs(h: Harness, forgery: dict[str, Any]) -> None:
    headers = h.auth(ALICE)
    baseline = h.client.post("/t/whoami", headers=headers, json={}).json()
    extra_headers = {**headers, **forgery.get("headers", {})}
    h.client.cookies.clear()
    for name, value in forgery.get("cookies", {}).items():
        h.client.cookies.set(name, value)
    forged = h.client.post(
        "/t/whoami",
        headers=extra_headers,
        params=forgery.get("params"),
        json=forgery.get("json", {}),
    )
    assert forged.status_code == 200
    assert forged.json() == baseline
    assert baseline["allowed_domains"] == [FINANCE]
    denied = h.client.get(
        f"/t/domains/{HR}/data", headers=extra_headers, params=forgery.get("params")
    )
    assert denied.status_code == 403
    h.client.cookies.clear()


def test_expired_grant_stops_allowing(h: Harness) -> None:
    assert h.client.get(f"/t/resources/{AGENT}", headers=h.auth(ALICE)).status_code == 200
    h.clock.advance(1801)
    response = h.client.get(f"/t/resources/{AGENT}", headers=h.auth(ALICE))
    assert response.status_code == 403
    assert response.json()["reason"] == "target_out_of_scope"


def test_expired_role_stops_allowing() -> None:
    hh = harness(policy(ALICE, role(Role.VIEWER, FINANCE, expires_in=60)))
    assert hh.client.get("/t/data", headers=hh.auth(ALICE)).status_code == 200
    hh.clock.advance(61)
    response = hh.client.get("/t/data", headers=hh.auth(ALICE))
    assert response.status_code == 403
    assert response.json()["reason"] == "permission_missing"


class CountingSource:
    def __init__(self, inner: ScopeDeriver) -> None:
        self.inner = inner
        self.calls = 0

    async def derive(self, claims: VerifiedClaims) -> ScopeDerivation:
        self.calls += 1
        return await self.inner.derive(claims)


def _finance(request: Request, scope: IdentityScope) -> AuthzTarget:
    return AuthzTarget(domain_id=FINANCE)


def test_scope_is_derived_once_per_request() -> None:
    router = APIRouter()

    @router.get(
        "/both",
        dependencies=[
            Depends(require(Permission.DATA_READ)),
            Depends(require(Permission.DATA_READ, _finance)),
        ],
    )
    async def both(scope: Annotated[IdentityScope, Depends(current_scope)]) -> dict[str, str]:
        return {"scope_hash": scope.scope_hash}

    hh = harness(policy(ALICE, role(Role.VIEWER, FINANCE)), routers={"/t": router})
    counting = CountingSource(hh.deriver)
    configure_authz(hh.app, authenticator=hh.validator, scope_source=counting, clock=hh.clock)
    response = hh.client.get("/t/both", headers=hh.auth(ALICE))
    assert response.status_code == 200
    assert counting.calls == 1


@pytest.mark.parametrize("bad", ["data.write", "admin", "*", ""])
def test_unknown_permission_fails_at_declaration(bad: str) -> None:
    with pytest.raises(InvalidSchemaError):
        require(bad)


def test_router_routes_all_return_the_server_scope(h: Harness) -> None:
    # Sanity: build_router is importable standalone and every success echoes the derived scope.
    assert build_router().routes
    body = h.client.get(f"/t/domains/{FINANCE}/data", headers=h.auth(ALICE)).json()
    assert body["scope_hash"].startswith("sha256:")
