"""Fail-closed behavior: policy store outage/timeout is 503 (never 200, never allow), any
authorization-path failure denies, the recorder hook cannot turn a deny into an allow, and an AST
scan proves no exception handler in the authz package returns, passes or assigns its way out.
"""

from __future__ import annotations

import ast
import asyncio
from pathlib import Path
from typing import Any

import neurosphere_api.authz
import pytest
from fastapi import APIRouter, Depends, Request
from fastapi.testclient import TestClient
from neurosphere_api.authz import AuthzTarget, configure_authz, require
from neurosphere_core.auth.jwt import VerifiedClaims
from neurosphere_core.auth.scope import (
    InMemoryPolicyRepository,
    Permission,
    PolicyHead,
    Role,
    ScopeDerivation,
    ScopeDerivationConfig,
    ScopeDeriver,
)
from neurosphere_core.cloud import CloudName
from neurosphere_core.errors import (
    CapabilityUnavailableError,
    DependencyTransientError,
    InvalidSchemaError,
    StaleVersionError,
)
from neurosphere_core.scope import IdentityScope

from .authz_helpers import (
    ALICE,
    CUSTOMER,
    FINANCE,
    HR,
    TENANT,
    FakeClock,
    RecordingDenials,
    harness,
    make_app,
    make_deriver,
    make_validator,
    policy,
    pseudonymizer,
    role,
)

ALICE_VIEWER = policy(ALICE, role(Role.VIEWER, FINANCE))
PROTECTED: list[tuple[str, str]] = [
    ("GET", "/t/data"),
    ("POST", "/t/whoami"),
    ("GET", f"/t/domains/{FINANCE}/data"),
    ("GET", f"/t/domains/{HR}/data"),
    ("GET", "/t/resources/commercial:contoso:foundry:agent:support-bot"),
    ("POST", "/t/config"),
]


def _reason(response: Any) -> str:
    return response.json().get("reason", "")


# --------------------------------------------------------------------------- policy store


@pytest.mark.parametrize(("method", "path"), PROTECTED)
@pytest.mark.parametrize("error", [ConnectionError("down"), TimeoutError(), RuntimeError("x")])
def test_policy_store_outage_is_503_on_every_protected_route(
    method: str, path: str, error: Exception
) -> None:
    h = harness(ALICE_VIEWER)
    h.repo.fail_with(error)
    response = h.client.request(method, path, headers=h.auth(ALICE))
    assert response.status_code == 503
    body = response.json()
    assert body["code"] == "dependency_transient"
    assert body["reason"] == "policy_store_unavailable"


class HangingRepository(InMemoryPolicyRepository):
    async def get_policy_head(self, customer_id: str) -> PolicyHead | None:
        await asyncio.Event().wait()
        raise AssertionError("unreachable")


def test_policy_store_timeout_is_503() -> None:
    h = harness(ALICE_VIEWER)
    hanging = make_deriver(HangingRepository(), h.clock, store_timeout_seconds=0.05)
    configure_authz(h.app, authenticator=h.validator, scope_source=hanging, clock=h.clock)
    response = h.client.get("/t/data", headers=h.auth(ALICE))
    assert response.status_code == 503
    assert _reason(response) == "policy_store_unavailable"


def test_unexpired_cache_may_serve_but_expired_cache_never_extends_on_error() -> None:
    h = harness(ALICE_VIEWER)
    assert h.client.get("/t/data", headers=h.auth(ALICE)).status_code == 200
    h.repo.fail_with(ConnectionError("down"))
    h.clock.advance(10)  # inside the 30 s policy cache TTL (C14): stale-but-unexpired may serve
    assert h.client.get("/t/data", headers=h.auth(ALICE)).status_code == 200
    h.clock.advance(21)  # past the TTL: the store is consulted, fails, request fails closed
    first = h.client.get("/t/data", headers=h.auth(ALICE))
    second = h.client.get("/t/data", headers=h.auth(ALICE))
    assert (first.status_code, second.status_code) == (503, 503)


def test_missing_policy_head_denies_rather_than_errors() -> None:
    h = harness(ALICE_VIEWER, policy_version=None)
    response = h.client.get("/t/data", headers=h.auth(ALICE))
    assert response.status_code == 403
    assert _reason(response) == "permission_missing"


# --------------------------------------------------------------------------- revocation


class Revocation:
    def __init__(self, answer: Any = False, error: Exception | None = None) -> None:
        self.answer = answer
        self.error = error

    async def is_revoked(self, principal_id: str, issued_at: Any) -> bool:
        if self.error is not None:
            raise self.error
        return self.answer


@pytest.mark.parametrize(
    ("checker", "status", "reason"),
    [
        (Revocation(answer=True), 403, "principal_revoked"),
        (Revocation(error=ConnectionError("down")), 503, "revocation_unavailable"),
        (Revocation(answer="maybe"), 502, "revocation_unavailable"),
        (Revocation(answer=False), 200, None),
    ],
)
def test_revocation_outcomes(checker: Revocation, status: int, reason: str | None) -> None:
    h = harness(ALICE_VIEWER, revocation_checker=checker)
    response = h.client.get("/t/data", headers=h.auth(ALICE))
    assert response.status_code == status
    if reason is not None:
        assert _reason(response) == reason


# --------------------------------------------------------------------------- scope source


class BrokenSource:
    def __init__(self, behavior: str) -> None:
        self.behavior = behavior

    async def derive(self, claims: VerifiedClaims) -> ScopeDerivation:
        if self.behavior == "hang":
            await asyncio.Event().wait()
        if self.behavior == "runtime":
            raise RuntimeError("policy store exploded")
        if self.behavior == "schema":
            raise InvalidSchemaError("bad", reason="config")
        if self.behavior == "stale":
            raise StaleVersionError()
        if self.behavior == "capability":
            raise CapabilityUnavailableError("region_unsupported")
        if self.behavior == "cancelled-like":
            raise LookupError("missing")
        return None  # type: ignore[return-value]  # "junk": a source returning no scope


@pytest.mark.parametrize(
    ("behavior", "reason"),
    [
        ("hang", "authz_timeout"),
        ("runtime", "authz_unavailable"),
        ("schema", "authz_unavailable"),
        ("stale", "authz_unavailable"),
        ("capability", "authz_unavailable"),
        ("cancelled-like", "authz_unavailable"),
        ("junk", "authz_invalid_scope"),
    ],
)
def test_scope_source_failure_never_allows(behavior: str, reason: str) -> None:
    h = harness(ALICE_VIEWER)
    configure_authz(
        h.app,
        authenticator=h.validator,
        scope_source=BrokenSource(behavior),
        clock=h.clock,
        timeout_seconds=0.05,
    )
    for method, path in PROTECTED:
        response = h.client.request(method, path, headers=h.auth(ALICE))
        assert response.status_code == 503, (method, path, response.text)
        assert response.json()["code"] == "dependency_transient"
        assert _reason(response) == reason


def test_unconfigured_authz_is_503_not_allow() -> None:
    client = TestClient(make_app(), raise_server_exceptions=False)
    for method, path in PROTECTED:
        response = client.request(method, path, headers={"Authorization": "Bearer a.b.c"})
        assert response.status_code == 503
        assert _reason(response) == "authz_unconfigured"


def test_configure_rejects_mismatched_cloud_binding() -> None:
    clock = FakeClock()
    gov = ScopeDeriver(
        ScopeDerivationConfig(cloud=CloudName.GOVERNMENT, tenant_id=TENANT, customer_id=CUSTOMER),
        policy_repository=InMemoryPolicyRepository(),
        pseudonymizer=pseudonymizer(),
        clock=clock,
    )
    with pytest.raises(InvalidSchemaError):
        configure_authz(make_app(), authenticator=make_validator(clock), scope_source=gov)


# --------------------------------------------------------------------------- resolvers


def _raising(request: Request, scope: IdentityScope) -> AuthzTarget:
    raise ValueError("cannot parse target")


def _none(request: Request, scope: IdentityScope) -> AuthzTarget | None:
    return None


def _transient(request: Request, scope: IdentityScope) -> AuthzTarget:
    raise DependencyTransientError("catalog down", reason="catalog_unavailable")


def _wrong_type(request: Request, scope: IdentityScope) -> Any:
    return {"domain_id": FINANCE}


@pytest.mark.parametrize(
    ("resolver", "status", "reason"),
    [
        (_raising, 403, "target_unresolved"),
        (_none, 403, "target_unresolved"),
        (_wrong_type, 403, "target_unresolved"),
        (_transient, 503, "catalog_unavailable"),
    ],
)
def test_resolver_failure_denies(resolver: Any, status: int, reason: str) -> None:
    router = APIRouter()

    @router.get("/x", dependencies=[Depends(require(Permission.DATA_READ, resolver))])
    async def x() -> dict[str, str]:
        return {"ok": "yes"}

    h = harness(ALICE_VIEWER, routers={"/t": router})
    response = h.client.get("/t/x", headers=h.auth(ALICE))
    assert response.status_code == status
    assert _reason(response) == reason


# --------------------------------------------------------------------------- recorder hook


def test_denial_is_recorded_with_metadata_only() -> None:
    denials = RecordingDenials()
    h = harness(ALICE_VIEWER, denials=denials)
    token = h.token(ALICE)
    response = h.client.get(f"/t/domains/{HR}/data", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 403
    (attempt,) = denials.attempts
    assert attempt.permission == "data.read"
    assert attempt.reason == "target_out_of_scope"
    assert attempt.path == f"/t/domains/{HR}/data"
    assert attempt.domain_id == HR
    assert attempt.method == "GET"
    flat = repr((attempt.permission, attempt.reason, attempt.path, attempt.scope))
    assert token not in flat and ALICE not in flat
    for segment in token.split("."):
        assert segment not in flat


def test_allowed_requests_are_not_recorded_as_denials() -> None:
    denials = RecordingDenials()
    h = harness(ALICE_VIEWER, denials=denials)
    assert h.client.get("/t/data", headers=h.auth(ALICE)).status_code == 200
    assert denials.attempts == []


@pytest.mark.parametrize(
    ("method", "path", "status", "reason"),
    [
        ("GET", "/t/config", 403, "permission_missing"),
        ("POST", "/t/config", 503, "audit_write_failed"),
    ],
)
def test_recorder_failure_never_allows(method: str, path: str, status: int, reason: str) -> None:
    h = harness(ALICE_VIEWER, denials=RecordingDenials(error=ConnectionError("audit down")))
    response = h.client.request(method, path, headers=h.auth(ALICE))
    assert response.status_code == status
    assert _reason(response) == reason


# --------------------------------------------------------------------------- AST scan

AUTHZ_DIR = Path(neurosphere_api.authz.__file__).parent
_ALLOWED_HANDLER_STATEMENTS = (ast.Raise, ast.Expr, ast.If)


def _handler_violations(statements: list[ast.stmt], where: str) -> list[str]:
    found: list[str] = []
    for stmt in statements:
        if not isinstance(stmt, _ALLOWED_HANDLER_STATEMENTS):
            found.append(f"{where}:{stmt.lineno}: {type(stmt).__name__} in except handler")
            continue
        if isinstance(stmt, ast.Expr) and not isinstance(stmt.value, ast.Call | ast.Await):
            found.append(f"{where}:{stmt.lineno}: bare expression in except handler")
        if isinstance(stmt, ast.If):
            found += _handler_violations(stmt.body, where)
            found += _handler_violations(stmt.orelse, where)
    return found


def scan_source(source: str, where: str = "<src>") -> list[str]:
    """Exception handlers may only raise, log (call) or branch to those; nothing else."""
    found: list[str] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.ExceptHandler):
            if node.type is None:
                found.append(f"{where}:{node.lineno}: bare except")
            found += _handler_violations(node.body, where)
        if isinstance(node, ast.Name | ast.Attribute):
            name = node.id if isinstance(node, ast.Name) else node.attr
            if name == "suppress":
                found.append(f"{where}:{node.lineno}: contextlib.suppress swallows errors")
    return found


def test_authz_modules_have_no_allow_on_error_branch() -> None:
    files = sorted(AUTHZ_DIR.glob("*.py"))
    assert len(files) >= 6
    violations: list[str] = []
    handlers = 0
    for path in files:
        source = path.read_text(encoding="utf-8")
        handlers += sum(isinstance(n, ast.ExceptHandler) for n in ast.walk(ast.parse(source)))
        violations += scan_source(source, path.name)
    assert violations == []
    assert handlers >= 5  # the scan is not vacuous


@pytest.mark.parametrize(
    "bad",
    [
        "try:\n    f()\nexcept Exception:\n    return scope\n",
        "try:\n    f()\nexcept Exception:\n    return None\n",
        "try:\n    f()\nexcept Exception:\n    pass\n",
        "try:\n    f()\nexcept Exception:\n    allowed = True\n",
        "try:\n    f()\nexcept:\n    raise\n",
        "try:\n    f()\nexcept Exception as e:\n    if e:\n        return True\n    raise\n",
        "with suppress(Exception):\n    f()\n",
        "for x in y:\n    try:\n        f()\n    except Exception:\n        continue\n",
    ],
)
def test_scanner_flags_allow_on_error_shapes(bad: str) -> None:
    wrapped = "def g():\n" + "".join("    " + line + "\n" for line in bad.splitlines())
    assert scan_source(wrapped) != []


def test_scanner_accepts_fail_closed_shapes() -> None:
    good = (
        "def g():\n"
        "    try:\n        f()\n"
        "    except KeyError:\n        raise\n"
        "    except Exception as exc:\n"
        "        if exc:\n            raise Denied() from exc\n"
        "        log.warning('x')\n"
    )
    assert scan_source(good) == []
