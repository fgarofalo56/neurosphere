"""Auditor read and chain-verify routes: deny-by-default seam, paging, tamper reporting."""

from __future__ import annotations

import asyncio
import hashlib
from collections.abc import Callable
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from neurosphere_api.app import create_app
from neurosphere_api.audit import (
    PERMISSION_AUDIT_READ,
    PERMISSION_AUDIT_VERIFY,
    ROUTE_PREFIX,
    build_router,
    register,
)
from neurosphere_api.routers import RouterRegistry
from neurosphere_contracts.scope.v1.identity_scope import IdentityScope as ContractScope
from neurosphere_core.audit import (
    AuditContext,
    AuditRepository,
    InMemoryAuditStore,
    build_allowed,
    build_before,
    build_denied,
    make_subject,
)
from neurosphere_core.cloud import Settings
from neurosphere_core.errors import ForbiddenError
from neurosphere_core.scope import IdentityScope

CHAIN = "contoso.domain-retail"
N = 7
_FORGED_MARKER = "corr-forged-marker"


def _ctx() -> AuditContext:
    contract = ContractScope.model_validate(
        {
            "schema_version": "1.0.0",
            "cloud": "commercial",
            "customer_id": "contoso",
            "principal": {
                "principal_id": "commercial:contoso:entra:person:psn_0123456789abcdef",
                "principal_pseudonym": "p-auditor-01",
                "principal_kind": "user",
            },
            "roles": [],
            "allowed_domains": ["commercial:contoso:catalog:domain:retail"],
            "allowed_resources": [],
            "policy_version": "v1",
            "derived_at": "2026-10-10T00:00:00Z",
            "scope_hash": "sha256:" + hashlib.sha256(b"auditor").hexdigest(),
        }
    )
    scope = IdentityScope._from_verified_contract(contract)  # pyright: ignore[reportPrivateUsage]
    return AuditContext.from_scope(
        scope, correlation_id="corr-1", operation="catalog.read", channel="rest"
    )


def _filled_store(n: int = N) -> InMemoryAuditStore:
    store = InMemoryAuditStore()
    repo = AuditRepository(store)
    ctx = _ctx()
    sub = make_subject(
        "commercial:contoso:foundry:model_deployment:eastus2/chat-prod", "model_deployment"
    )

    async def fill() -> None:
        for i in range(n):
            draft = (
                build_allowed(ctx, sub),
                build_before(ctx, sub),
                build_denied(ctx, code="forbidden", reason="domain_out_of_scope"),
            )[i % 3]
            await repo.append(CHAIN, draft)

    asyncio.run(fill())
    return store


def _allow_recording(seen: list[str]) -> Callable[[str], Callable[[], Any]]:
    def factory(permission: str) -> Callable[[], Any]:
        seen.append(permission)

        async def allow() -> None:
            return None

        return allow

    return factory


def _app(
    store: InMemoryAuditStore | None,
    require_permission: Callable[[str], Callable[..., Any]] | None = None,
) -> FastAPI:
    router = (
        build_router(require_permission=require_permission)
        if require_permission is not None
        else build_router()
    )
    app = create_app(Settings(env="local"), extra_routers={ROUTE_PREFIX: router})
    if store is not None:
        app.state.audit_repository = AuditRepository(store)
    return app


def _client(app: FastAPI) -> TestClient:
    return TestClient(app, raise_server_exceptions=False)


RECORDS = f"{ROUTE_PREFIX}/chains/{CHAIN}/records"
VERIFY = f"{ROUTE_PREFIX}/chains/{CHAIN}/verify"


# -- authz seam ----------------------------------------------------------------------------------


@pytest.mark.parametrize("path", [RECORDS, VERIFY])
def test_default_seam_denies_everything(path: str) -> None:
    response = _client(_app(_filled_store())).get(path)
    assert response.status_code == 403
    body = response.json()
    assert body["code"] == "forbidden" and body["reason"] == "authz_not_wired"
    assert "items" not in body and "ok" not in body


@pytest.mark.parametrize("path", [RECORDS, VERIFY])
def test_permission_is_checked_before_the_repository_is_touched(path: str) -> None:
    # No repository configured: a deny must still be 403, proving the permission ran first.
    assert _client(_app(None)).get(path).status_code == 403


def test_routes_request_the_documented_permissions() -> None:
    seen: list[str] = []
    _app(_filled_store(1), _allow_recording(seen))
    assert seen == [PERMISSION_AUDIT_READ, PERMISSION_AUDIT_VERIFY]


def test_permission_dependency_can_deny_one_route() -> None:
    def factory(permission: str) -> Callable[[], Any]:
        async def check() -> None:
            if permission == PERMISSION_AUDIT_VERIFY:
                raise ForbiddenError(reason="permission_missing")

        return check

    client = _client(_app(_filled_store(), factory))
    assert client.get(RECORDS).status_code == 200
    denied = client.get(VERIFY)
    assert denied.status_code == 403 and denied.json()["reason"] == "permission_missing"


def test_register_hook_uses_deny_all_by_default() -> None:
    registry = RouterRegistry()
    register(registry)
    # The successor prefix and its deprecated alias (PRP-29 item 4).
    assert registry.prefixes == (ROUTE_PREFIX, "/audit")


# -- read --------------------------------------------------------------------------------------


def test_read_pages_through_the_whole_chain() -> None:
    client = _client(_app(_filled_store(), _allow_recording([])))
    sequences: list[int] = []
    cursor: str | None = None
    pages = 0
    while True:
        params: dict[str, Any] = {"page_size": 3}
        if cursor is not None:
            params["cursor"] = cursor
        response = client.get(RECORDS, params=params)
        assert response.status_code == 200
        body = response.json()
        sequences.extend(item["sequence"] for item in body["items"])
        pages += 1
        cursor = body["next_cursor"]
        if cursor is None:
            break
    assert sequences == list(range(N)) and pages == 3
    kinds = {item["kind"] for item in client.get(RECORDS).json()["items"]}
    assert kinds == {"after", "before", "denied"}


@pytest.mark.parametrize(
    "params", [{"page_size": 0}, {"page_size": 501}, {"cursor": "-1"}, {"cursor": "abc"}]
)
def test_invalid_paging_is_rejected(params: dict[str, Any]) -> None:
    response = _client(_app(_filled_store(1), _allow_recording([]))).get(RECORDS, params=params)
    assert response.status_code == 422
    assert response.json()["code"] == "invalid_schema"


@pytest.mark.parametrize("chain", ["UPPER", "has space", "-lead", "x" * 129])
def test_invalid_chain_id_is_rejected(chain: str) -> None:
    client = _client(_app(_filled_store(1), _allow_recording([])))
    assert client.get(f"{ROUTE_PREFIX}/chains/{chain}/records").status_code in (404, 422)


def test_unknown_chain_reads_empty() -> None:
    client = _client(_app(_filled_store(1), _allow_recording([])))
    body = client.get(f"{ROUTE_PREFIX}/chains/other.chain/records").json()
    assert body == {"items": [], "next_cursor": None}


def test_missing_repository_fails_closed_with_503() -> None:
    response = _client(_app(None, _allow_recording([]))).get(RECORDS)
    assert response.status_code == 503
    assert response.json()["reason"] == "audit_store_unconfigured"


@pytest.mark.parametrize("method", ["post", "put", "patch", "delete"])
@pytest.mark.parametrize("path", [RECORDS, VERIFY, f"{RECORDS}/0"])
def test_no_write_routes_exist(method: str, path: str) -> None:
    store = _filled_store(2)
    client = _client(_app(store, _allow_recording([])))
    response = getattr(client, method)(path)
    assert response.status_code in (404, 405)
    assert client.get(VERIFY).json()["ok"] is True


def test_router_only_declares_get() -> None:
    router = build_router(require_permission=_allow_recording([]))
    methods = {m for route in router.routes for m in getattr(route, "methods", set())}
    assert methods == {"GET"}


# -- verify ------------------------------------------------------------------------------------


def test_verify_reports_intact_chain() -> None:
    body = _client(_app(_filled_store(), _allow_recording([]))).get(VERIFY).json()
    assert body["ok"] is True and body["records_checked"] == N
    assert body["first_invalid_index"] is None


def test_verify_reports_first_tampered_index() -> None:
    store = _filled_store()
    doc = sorted(store.raw_documents(CHAIN), key=lambda d: d["sequence"])[4]
    doc["correlation_id"] = _FORGED_MARKER
    store.simulate_overwrite(CHAIN, 4, doc)
    response = _client(_app(store, _allow_recording([]))).get(VERIFY)
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is False
    assert (body["first_invalid_index"], body["first_invalid_sequence"]) == (4, 4)
    assert body["reason"] == "record_hash_mismatch"
    assert _FORGED_MARKER not in response.text


def test_verify_reports_removed_record() -> None:
    store = _filled_store()
    store.simulate_remove(CHAIN, 2)
    body = _client(_app(store, _allow_recording([]))).get(VERIFY).json()
    assert (body["ok"], body["first_invalid_index"], body["reason"]) == (
        False,
        2,
        "sequence_mismatch",
    )


def test_tampered_record_that_breaks_the_contract_returns_502_on_read() -> None:
    store = _filled_store()
    doc = sorted(store.raw_documents(CHAIN), key=lambda d: d["sequence"])[1]
    doc["kind"] = "erased"
    store.simulate_overwrite(CHAIN, 1, doc)
    client = _client(_app(store, _allow_recording([])))
    read = client.get(RECORDS)
    assert read.status_code == 502 and read.json()["reason"] == "audit_record_invalid"
    body = client.get(VERIFY).json()
    assert (body["first_invalid_index"], body["reason"]) == (1, "invalid_record")
