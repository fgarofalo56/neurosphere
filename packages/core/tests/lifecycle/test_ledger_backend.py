"""Ledger delete backend: single-partition delete, read-back absent, allocation untouched."""

from __future__ import annotations

from typing import Any

import pytest
from hitl_cosmos.fake_container import FakeContainer  # pyright: ignore[reportMissingImports]
from neurosphere_core.errors import CapabilityUnavailableError
from neurosphere_core.ledger.lifecycle_delete import LedgerLifecycleBackend, ledger_target
from neurosphere_core.lifecycle import (
    ActionKind,
    Effect,
    JobStatus,
    LifecycleRequest,
    TargetRef,
    load_policy,
)

from .lifecycle_helpers import make_ctx, make_rig, policy_for


def _container() -> FakeContainer:
    return FakeContainer(("/customer_id",))


def _put(
    container: FakeContainer,
    entry_id: str,
    *,
    customer: str = "contoso",
    doc_type: str = "entry",
    occurred_at: str = "2026-01-02T03:04:05.000000Z",
) -> str:
    doc: dict[str, Any] = {
        "id": entry_id,
        "doc_type": doc_type,
        "customer_id": customer,
        "cloud": "commercial",
        "domain_id": "d1",
        "cost_category": "inference",
        "occurred_at": occurred_at,
        "observations": [{"note": "not exported"}],
    }
    container.docs[((customer,), entry_id)] = doc
    return entry_id


async def test_delete_then_read_back_absent() -> None:
    container = _container()
    entry = _put(container, "e1")
    backend = LedgerLifecycleBackend(container, customer_id="contoso")  # type: ignore[arg-type]
    found = await backend.read(entry)
    assert found is not None
    assert found["data_class"] == "ledger_entry"
    assert found["created_at"].year == 2026
    await backend.remove(entry)
    assert await backend.read(entry) is None
    assert container.docs == {}
    await backend.remove(entry)  # missing is a no-op


async def test_allocation_records_are_not_lifecycle_records() -> None:
    container = _container()
    alloc = _put(container, "a1", doc_type="allocation")
    backend = LedgerLifecycleBackend(container, customer_id="contoso")  # type: ignore[arg-type]
    assert await backend.read(alloc) is None
    await backend.remove(alloc)
    assert len(container.docs) == 1


async def test_other_customer_is_unreachable() -> None:
    container = _container()
    _put(container, "e1", customer="fabrikam")
    backend = LedgerLifecycleBackend(container, customer_id="contoso")  # type: ignore[arg-type]
    assert await backend.read("e1") is None
    await backend.remove("e1")
    assert len(container.docs) == 1
    assert await backend.page("ledger_entry", 10, None) == []
    for _, _, pk in container.queries:
        assert pk == ("contoso",)


async def test_paging_and_projection() -> None:
    container = _container()
    for i in range(3):
        _put(container, f"e{i}")
    _put(container, "z-alloc", doc_type="allocation")
    backend = LedgerLifecycleBackend(container, customer_id="contoso")  # type: ignore[arg-type]
    first = await backend.page("ledger_entry", 2, None)
    assert [d["id"] for d in first] == ["e0", "e1"]
    assert [d["id"] for d in await backend.page("ledger_entry", 2, "e1")] == ["e2"]
    assert await backend.page("other", 10, None) == []
    exported = await backend.project("e0")
    assert exported["cost_category"] == "inference"
    assert "observations" not in exported
    assert await backend.page_by_subject("anyone", 10, None) == []
    with pytest.raises(CapabilityUnavailableError):
        await backend.redact_subject("e0")


def test_audit_container_is_refused() -> None:
    backend = LedgerLifecycleBackend(_container(), customer_id="contoso")  # type: ignore[arg-type]
    for name in ("audit", "audit_tail"):
        with pytest.raises(ValueError):
            ledger_target(name, backend)
    assert ledger_target("cost_ledger", backend).target_kind == "ledger"


async def test_engine_deletes_through_the_ledger_target() -> None:
    container = _container()
    _put(container, "e1")
    backend = LedgerLifecycleBackend(container, customer_id="contoso")  # type: ignore[arg-type]
    rig = make_rig(
        mode="execute",
        state=load_policy(policy_for("ledger_entry")),
        target=ledger_target("cost_ledger", backend),  # type: ignore[arg-type]
    )
    request = LifecycleRequest(
        action=ActionKind.DELETE,
        target=TargetRef(target_kind="ledger", container="cost_ledger", record_id="e1"),
    )
    out = await rig.engine.submit(request, make_ctx())
    assert (out.status, out.effect, out.verified) == (JobStatus.COMPLETED, Effect.DELETED, True)
    assert container.docs == {}
