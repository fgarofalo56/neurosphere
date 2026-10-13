"""Append-only guarantees: no update/delete surface, no mutating SDK call, fail-closed writes."""

from __future__ import annotations

import ast
import inspect
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any, cast

import pytest
from azure.core import MatchConditions
from azure.core.exceptions import ServiceRequestError
from azure.cosmos.aio import ContainerProxy
from azure.cosmos.exceptions import (
    CosmosAccessConditionFailedError,
    CosmosResourceExistsError,
    CosmosResourceNotFoundError,
)
from neurosphere_core import audit as audit_pkg
from neurosphere_core.audit import (
    AuditRepository,
    AuditStore,
    InMemoryAuditStore,
    SequenceTakenError,
    TailConflictError,
    TailPointer,
    build_after,
    build_before,
    build_denied,
    run_audited_mutation,
)
from neurosphere_core.audit.cosmos_store import CosmosAuditStore
from neurosphere_core.errors import DependencyTransientError, ForbiddenError

from .audit_helpers import CHAIN, make_ctx, make_repo, mixed_drafts, subject

_AUDIT_SRC = Path(audit_pkg.__file__).resolve().parent
_REFUSED = ("update", "delete", "replace", "upsert", "patch", "remove")
_ALLOWED_PUBLIC = {"append", "read_range", "tail", "verify", *_REFUSED}


# -- repository surface --------------------------------------------------------------------------


@pytest.mark.parametrize("name", _REFUSED)
def test_update_and_delete_style_calls_raise_forbidden(name: str) -> None:
    repo = make_repo()
    with pytest.raises(ForbiddenError) as info:
        getattr(repo, name)(CHAIN, 0, {"kind": "denied"})
    assert info.value.reason == "audit_append_only"
    assert info.value.http_status == 403


def test_repository_public_surface_is_append_read_verify_only() -> None:
    public = {
        name
        for name, member in inspect.getmembers(AuditRepository)
        if not name.startswith("_") and callable(member)
    }
    assert public == _ALLOWED_PUBLIC


def test_store_port_has_no_record_mutation_operation() -> None:
    methods = {
        name
        for name, member in inspect.getmembers(AuditStore)
        if not name.startswith("_") and callable(member)
    }
    assert methods == {"read_tail", "create_record", "read_record", "write_tail", "query_range"}


def _sdk_calls() -> list[tuple[str, str, str]]:
    """(file, enclosing function, attribute) for every ``x.<attr>(...)`` call in the package."""
    found: list[tuple[str, str, str]] = []
    for path in _AUDIT_SRC.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for func in ast.walk(tree):
            if not isinstance(func, ast.FunctionDef | ast.AsyncFunctionDef):
                continue
            for node in ast.walk(func):
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                    found.append((path.name, func.name, node.func.attr))
    return found


def test_no_code_path_calls_mutating_cosmos_operations() -> None:
    calls = _sdk_calls()
    assert calls
    attrs = {attr for _, _, attr in calls}
    assert not attrs & {
        "upsert_item",
        "patch_item",
        "delete_item",
        "delete_all_items_by_partition_key",
    }
    replace_sites = {(f, fn) for f, fn, attr in calls if attr == "replace_item"}
    assert replace_sites == {("cosmos_store.py", "write_tail")}  # tail pointer only


async def test_returned_records_are_copies_and_storage_is_unchanged() -> None:
    store = InMemoryAuditStore()
    repo = make_repo(store)
    record = await repo.append(CHAIN, mixed_drafts(1)[0])
    record.sequence = 99
    record.correlation_id = "corr-changed"
    stored = (await repo.read_range(CHAIN))[0]
    assert stored.sequence == 0 and stored.correlation_id == "corr-7c41e2"
    assert (await repo.verify(CHAIN)).ok


async def test_appending_never_rewrites_earlier_records() -> None:
    store = InMemoryAuditStore()
    repo = make_repo(store)
    for draft in mixed_drafts(5):
        await repo.append(CHAIN, draft)
    before = {d["sequence"]: d for d in store.raw_documents(CHAIN)}
    for draft in mixed_drafts(5):
        await repo.append(CHAIN, draft)
    after = {d["sequence"]: d for d in store.raw_documents(CHAIN)}
    assert all(after[seq] == doc for seq, doc in before.items())


async def test_store_create_is_create_only() -> None:
    store = InMemoryAuditStore()
    repo = make_repo(store)
    record = await repo.append(CHAIN, mixed_drafts(1)[0])
    with pytest.raises(SequenceTakenError):
        await store.create_record(CHAIN, 0, {**record.model_dump(mode="json"), "kind": "denied"})
    assert store.raw_documents(CHAIN)[0] == record.model_dump(mode="json")


# -- fail closed -----------------------------------------------------------------------------------


async def test_failed_write_raises_dependency_transient() -> None:
    store = InMemoryAuditStore()
    store.fail_with = ConnectionError("store down")
    with pytest.raises(DependencyTransientError) as info:
        await make_repo(store).append(CHAIN, mixed_drafts(1)[0])
    assert info.value.reason == "audit_write_failed"
    assert info.value.status == 503


async def test_mutation_aborts_when_before_record_cannot_be_written() -> None:
    store = InMemoryAuditStore()
    store.fail_with = ConnectionError("store down")
    ctx = make_ctx()
    calls: list[str] = []

    async def mutate() -> str:
        calls.append("mutated")
        return "etag-2"

    with pytest.raises(DependencyTransientError):
        await run_audited_mutation(
            make_repo(store),
            CHAIN,
            before=build_before(ctx, subject("etag-1")),
            mutate=mutate,
            after=lambda v: build_after(ctx, subject(v), result="succeeded", verified=True),
        )
    assert calls == []


async def test_audited_mutation_writes_before_and_after() -> None:
    repo = make_repo()
    ctx = make_ctx()

    async def mutate() -> str:
        return "etag-2"

    result = await run_audited_mutation(
        repo,
        CHAIN,
        before=build_before(ctx, subject("etag-1")),
        mutate=mutate,
        after=lambda v: build_after(ctx, subject(v), result="succeeded", verified=True),
    )
    assert result == "etag-2"
    kinds = [
        (r.kind, r.subject.target_version if r.subject else None)
        for r in await repo.read_range(CHAIN)
    ]
    assert kinds == [("before", "etag-1"), ("after", "etag-2")]


async def test_failed_mutation_records_error_outcome_and_reraises() -> None:
    repo = make_repo()
    ctx = make_ctx()

    async def mutate() -> str:
        raise RuntimeError("target rejected change")

    with pytest.raises(RuntimeError):
        await run_audited_mutation(
            repo,
            CHAIN,
            before=build_before(ctx, subject()),
            mutate=mutate,
            after=lambda v: build_after(ctx, subject(v), result="succeeded", verified=True),
            on_error=lambda _e: build_after(
                ctx, subject(), result="failed", verified=False, detail="target_rejected"
            ),
        )
    records = await repo.read_range(CHAIN)
    assert [r.kind for r in records] == ["before", "after"]
    assert records[1].outcome is not None and records[1].outcome.result == "failed"


class _FailAfterFirst(InMemoryAuditStore):
    async def create_record(self, chain_id: str, sequence: int, document: Any) -> None:
        if sequence >= 1:
            raise ConnectionError("lost")
        await super().create_record(chain_id, sequence, document)


async def test_failed_after_record_surfaces_as_error() -> None:
    ctx = make_ctx()

    async def mutate() -> str:
        return "etag-2"

    with pytest.raises(DependencyTransientError):
        await run_audited_mutation(
            make_repo(_FailAfterFirst()),
            CHAIN,
            before=build_before(ctx, subject()),
            mutate=mutate,
            after=lambda v: build_after(ctx, subject(v), result="succeeded", verified=True),
        )


# -- Cosmos store against a fake container ---------------------------------------------------


class _FakeContainer:
    """Minimal async ContainerProxy double: records every call; Cosmos-like conditions."""

    def __init__(self) -> None:
        self.docs: dict[tuple[str, str], dict[str, Any]] = {}
        self.calls: list[tuple[str, str]] = []
        self.queries: list[dict[str, Any]] = []
        self._etag = 0
        self.outage = False

    def _check(self) -> None:
        if self.outage:
            raise ServiceRequestError("unreachable")

    def _stamp(self, doc: dict[str, Any]) -> dict[str, Any]:
        self._etag += 1
        return {**doc, "_etag": f'"{self._etag}"', "_rid": "x", "_ts": 1}

    async def create_item(self, body: dict[str, Any], **_: Any) -> dict[str, Any]:
        self._check()
        self.calls.append(("create_item", body["id"]))
        key = (body["chain_id"], body["id"])
        if key in self.docs:
            raise CosmosResourceExistsError(message="exists")
        self.docs[key] = self._stamp(body)
        return self.docs[key]

    async def read_item(self, item: str, partition_key: str, **_: Any) -> dict[str, Any]:
        self._check()
        self.calls.append(("read_item", item))
        if (partition_key, item) not in self.docs:
            raise CosmosResourceNotFoundError(message="missing")
        return dict(self.docs[(partition_key, item)])

    async def replace_item(
        self, item: str, body: dict[str, Any], *, etag: str, match_condition: Any, **_: Any
    ) -> dict[str, Any]:
        self._check()
        self.calls.append(("replace_item", item))
        assert match_condition == MatchConditions.IfNotModified
        key = (body["chain_id"], item)
        if self.docs.get(key, {}).get("_etag") != etag:
            raise CosmosAccessConditionFailedError(message="precondition")
        self.docs[key] = self._stamp(body)
        return self.docs[key]

    def query_items(
        self, *, query: str, parameters: list[dict[str, Any]], partition_key: str, **_: Any
    ) -> AsyncIterator[dict[str, Any]]:
        self._check()
        self.queries.append({"query": query, "parameters": parameters})
        values = {p["name"]: p["value"] for p in parameters}

        async def gen() -> AsyncIterator[dict[str, Any]]:
            for (chain, _id), doc in list(self.docs.items()):
                if (
                    chain == partition_key
                    and doc.get("doc_type") == values["@doc_type"]
                    and values["@start"] <= doc["sequence"] < values["@stop"]
                ):
                    yield dict(doc)

        return gen()


def _cosmos() -> tuple[CosmosAuditStore, _FakeContainer]:
    fake = _FakeContainer()
    return CosmosAuditStore(cast(ContainerProxy, fake)), fake


async def test_cosmos_store_round_trip_and_verify() -> None:
    store, fake = _cosmos()
    repo = AuditRepository(store)
    for draft in mixed_drafts(6):
        await repo.append(CHAIN, draft)
    records = await repo.read_range(CHAIN)
    assert [r.sequence for r in records] == list(range(6))  # system fields stripped, validates
    assert (await repo.verify(CHAIN)).ok
    record_ops = {op for op, doc_id in fake.calls if doc_id.startswith("rec-")}
    assert record_ops == {"create_item"}  # records are only ever created
    assert {i for op, i in fake.calls if op == "replace_item"} == {"tail"}


async def test_cosmos_existing_sequence_maps_to_sequence_taken() -> None:
    store, _ = _cosmos()
    repo = AuditRepository(store)
    record = await repo.append(CHAIN, mixed_drafts(1)[0])
    with pytest.raises(SequenceTakenError):
        await store.create_record(CHAIN, 0, record.model_dump(mode="json"))


async def test_cosmos_tail_precondition_failure_maps_to_tail_conflict() -> None:
    store, _ = _cosmos()
    tail = TailPointer(chain_id=CHAIN, sequence=0, record_hash="sha256:" + "a" * 64)
    await store.write_tail(tail, if_match=None)
    with pytest.raises(TailConflictError):
        await store.write_tail(tail, if_match=None)  # already exists
    with pytest.raises(TailConflictError):
        await store.write_tail(tail, if_match='"stale"')


async def test_cosmos_query_is_parameterized_single_partition() -> None:
    store, fake = _cosmos()
    await store.query_range(CHAIN, 0, 10)
    assert "@start" in fake.queries[0]["query"] and CHAIN not in fake.queries[0]["query"]


async def test_cosmos_outage_fails_closed() -> None:
    store, fake = _cosmos()
    fake.outage = True
    with pytest.raises(DependencyTransientError) as info:
        await AuditRepository(store).append(
            CHAIN, build_denied(make_ctx(), code="forbidden", reason="x_y")
        )
    assert info.value.reason == "audit_write_failed"


async def test_cosmos_store_rejects_mismatched_slot() -> None:
    store, _ = _cosmos()
    with pytest.raises(ValueError):
        await store.create_record(CHAIN, 3, {"chain_id": CHAIN, "sequence": 4})


async def test_separate_tail_container_keeps_records_container_create_read_query_only() -> None:
    records, tail = _FakeContainer(), _FakeContainer()
    store = CosmosAuditStore(cast(ContainerProxy, records), cast(ContainerProxy, tail))
    repo = AuditRepository(store)
    for draft in mixed_drafts(6):
        await repo.append(CHAIN, draft)
    assert (await repo.verify(CHAIN)).ok
    # A role granting only items/create + items/read + executeQuery is enough for this container.
    assert {op for op, _ in records.calls} <= {"create_item", "read_item"}
    assert records.queries  # range reads use query_items
    assert not any(doc_id == "tail" for _, doc_id in records.calls)
    # All tail traffic, including every replace, lands on the tail container.
    assert {i for op, i in tail.calls if op == "replace_item"} == {"tail"}
    assert {i for _, i in tail.calls} == {"tail"}
