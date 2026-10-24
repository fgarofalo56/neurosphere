"""Sandbox API (PRP-24 item 2): allowlist fails closed, permissions, 503, synthetic marking."""

from __future__ import annotations

from typing import Any

import pytest
from authz.authz_helpers import (  # pyright: ignore[reportMissingImports]
    ALICE,
    BOB,
    FINANCE,
    NOBODY,
    Harness,
    harness,
    policy,
    role,
)
from neurosphere_api.sandbox import PREFIX, build_router
from neurosphere_api.sandbox.models import SandboxKind
from neurosphere_api.sandbox.repository import (
    ALLOWED_DATABASE,
    ENTITIES_CONTAINER,
    RELATIONS_CONTAINER,
    CosmosSandboxStore,
    SandboxRepository,
)
from neurosphere_core.auth.scope import Role
from neurosphere_core.errors import InvalidSchemaError

ADMIN = "a1b2c3d4-0000-4000-8000-000000000003"


class RecordingStore:
    """Fake store: records every call; holds a few synthetic docs per container."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str]] = []
        self.docs: dict[str, list[dict[str, Any]]] = {
            ENTITIES_CONTAINER: [
                {"id": f"a{i}", "entity_type": "agent", "customer_id": "synthco"} for i in range(3)
            ]
            + [{"id": "d0", "entity_type": "domain", "customer_id": "synthco"}],
            RELATIONS_CONTAINER: [{"id": "r0", "relation_type": "uses"}],
        }

    async def count(self, database: str, container: str, kind: str | None) -> int:
        self.calls.append(("count", database, container))
        rows = self.docs[container]
        return len(rows) if kind is None else sum(r.get("entity_type") == kind for r in rows)

    async def list_items(
        self, database: str, container: str, kind: str, limit: int, offset: int
    ) -> list[dict[str, Any]]:
        self.calls.append(("list", database, container))
        rows = [r for r in self.docs[container] if r.get("entity_type") == kind]
        return rows[offset : offset + limit]

    async def clear(self, database: str, container: str) -> int:
        self.calls.append(("clear", database, container))
        n = len(self.docs[container])
        self.docs[container] = []
        return n


def _make() -> tuple[Harness, RecordingStore]:
    fake = RecordingStore()
    h = harness(
        policy(ALICE, role(Role.VIEWER, FINANCE)),
        policy(BOB, role(Role.ANALYST, FINANCE)),
        policy(ADMIN, role(Role.ADMIN, FINANCE)),
        routers={PREFIX: build_router()},
    )
    h.app.state.sandbox_repository = SandboxRepository(fake)
    return h, fake


# ------------------------------------------------------------------ allowlist (fail closed)

BAD_NAMES = [
    "catalog",
    "entities",
    "relations",
    "sandbox-catalog",  # look-alike prefix, not in the fixed set
    "sandbox-entities2",
    "sandbox-",
    "Sandbox-entities",
    "",
]


@pytest.mark.parametrize("name", BAD_NAMES)
def test_construction_refuses_non_allowlisted_container(name: str) -> None:
    store = RecordingStore()
    with pytest.raises(InvalidSchemaError) as info:
        SandboxRepository(store, containers=(ENTITIES_CONTAINER, name))
    assert info.value.reason == "sandbox_allowlist"
    assert store.calls == []


@pytest.mark.parametrize("name", ["neurosphere", "catalog", "sandbox-other", ""])
def test_construction_refuses_non_allowlisted_database(name: str) -> None:
    store = RecordingStore()
    with pytest.raises(InvalidSchemaError) as info:
        SandboxRepository(store, database=name)
    assert info.value.reason == "sandbox_allowlist"
    assert store.calls == []


@pytest.mark.parametrize("name", BAD_NAMES)
async def test_call_refuses_non_allowlisted_container_before_any_client_call(name: str) -> None:
    store = RecordingStore()
    repo = SandboxRepository(store)
    with pytest.raises(InvalidSchemaError):
        await repo.count_container(name)
    assert store.calls == []


async def test_cosmos_store_refuses_before_touching_the_client() -> None:
    class Exploding:
        def get_database_client(self, *_: object) -> Any:
            raise AssertionError("client must not be reached")

    store = CosmosSandboxStore(Exploding())  # pyright: ignore[reportArgumentType]
    for db, container in [("catalog", ENTITIES_CONTAINER), (ALLOWED_DATABASE, "entities")]:
        with pytest.raises(InvalidSchemaError):
            await store.count(db, container, None)
        with pytest.raises(InvalidSchemaError):
            await store.clear(db, container)


async def test_repository_only_touches_allowlisted_names() -> None:
    store = RecordingStore()
    repo = SandboxRepository(store)
    await repo.counts_by_kind()
    await repo.list_entities(SandboxKind.AGENT, 10, 0)
    await repo.reset()
    assert store.calls
    assert {(db, c) for _, db, c in store.calls} <= {
        (ALLOWED_DATABASE, ENTITIES_CONTAINER),
        (ALLOWED_DATABASE, RELATIONS_CONTAINER),
    }


def test_router_accepts_no_container_from_the_caller() -> None:
    h, store = _make()
    response = h.client.get(
        f"{PREFIX}/entities",
        headers={**h.auth(ALICE), "X-Sandbox": "1", "X-Container": "catalog"},
        params={"kind": "agent", "container": "catalog", "database": "catalog"},
    )
    assert response.status_code == 200
    assert {c for _, _, c in store.calls} == {ENTITIES_CONTAINER}


# ------------------------------------------------------------------ authorization


def test_unauthenticated_is_401() -> None:
    h, _ = _make()
    assert h.client.get(f"{PREFIX}/status").status_code == 401


@pytest.mark.parametrize(
    ("method", "path"),
    [("GET", "/status"), ("GET", "/entities?kind=agent"), ("POST", "/reset")],
)
def test_principal_without_policy_is_403(method: str, path: str) -> None:
    h, store = _make()
    response = h.client.request(method, PREFIX + path, headers=h.auth(NOBODY))
    assert response.status_code == 403
    assert store.calls == []


def test_viewer_cannot_reset() -> None:
    h, store = _make()
    response = h.client.post(f"{PREFIX}/reset", headers=h.auth(ALICE))
    assert response.status_code == 403
    assert store.calls == []
    assert len(store.docs[ENTITIES_CONTAINER]) == 4


@pytest.mark.parametrize(
    ("method", "path"),
    [("GET", "/status"), ("GET", "/entities?kind=agent"), ("POST", "/reset")],
)
def test_policy_store_down_is_503(method: str, path: str) -> None:
    h, store = _make()
    h.repo.fail_with(ConnectionError("down"))
    response = h.client.request(method, PREFIX + path, headers=h.auth(ADMIN))
    assert response.status_code == 503
    assert response.json()["code"] == "dependency_transient"
    assert store.calls == []


# ------------------------------------------------------------------ happy path


def test_status_marks_synthetic_and_counts() -> None:
    h, _ = _make()
    response = h.client.get(f"{PREFIX}/status", headers=h.auth(ALICE))
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["environment"] == "sandbox"
    assert body["synthetic"] is True
    assert body["customer_id"] == "synthco"
    assert body["database"] == ALLOWED_DATABASE
    assert body["counts"]["agent"] == 3
    assert body["counts"]["domain"] == 1
    assert set(body["counts"]) == {k.value for k in SandboxKind}
    assert body["relations"] == 1
    assert body["total"] == 5


def test_entities_paging_and_synthetic_marker() -> None:
    h, _ = _make()
    first = h.client.get(
        f"{PREFIX}/entities", headers=h.auth(ALICE), params={"kind": "agent", "limit": 2}
    ).json()
    assert first["synthetic"] is True
    assert first["environment"] == "sandbox"
    assert [i["id"] for i in first["items"]] == ["a0", "a1"]
    assert first["next_offset"] == 2
    second = h.client.get(
        f"{PREFIX}/entities",
        headers=h.auth(ALICE),
        params={"kind": "agent", "limit": 2, "offset": first["next_offset"]},
    ).json()
    assert [i["id"] for i in second["items"]] == ["a2"]
    assert second["next_offset"] is None


@pytest.mark.parametrize(
    "params",
    [{"kind": "catalog"}, {"kind": "agent", "limit": 0}, {"kind": "agent", "limit": 101}, {}],
)
def test_kind_is_closed_and_page_size_bounded(params: dict[str, Any]) -> None:
    h, store = _make()
    response = h.client.get(f"{PREFIX}/entities", headers=h.auth(ALICE), params=params)
    assert response.status_code == 422
    assert store.calls == []


def test_admin_reset_clears_only_sandbox_containers() -> None:
    h, store = _make()
    response = h.client.post(f"{PREFIX}/reset", headers=h.auth(ADMIN))
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["synthetic"] is True
    assert body["deleted"] == {ENTITIES_CONTAINER: 4, RELATIONS_CONTAINER: 1}
    assert {c for _, _, c in store.calls} == {ENTITIES_CONTAINER, RELATIONS_CONTAINER}
