"""Catalog delete backend: delete then read back absent, scoped to one customer."""

from __future__ import annotations

import pytest
from hitl_cosmos.fake_container import FakeContainer  # pyright: ignore[reportMissingImports]
from neurosphere_core.catalog.lifecycle_delete import CatalogLifecycleBackend, catalog_target
from neurosphere_core.catalog.partitioning import PartitionKeyShape, partition_key_paths
from neurosphere_core.catalog.repo.documents import make_doc
from neurosphere_core.errors import CapabilityUnavailableError
from neurosphere_core.lifecycle import (
    ActionKind,
    Effect,
    JobStatus,
    LifecycleRequest,
    TargetRef,
    load_policy,
)

from .lifecycle_helpers import make_ctx, make_rig, policy_for

DOMAIN = "commercial:contoso:catalog:domain:retail"
SHAPES = [PartitionKeyShape.FLAT_DOMAIN, PartitionKeyShape.TENANT_DOMAIN_SHARD]


def _container(shape: PartitionKeyShape) -> FakeContainer:
    return FakeContainer(partition_key_paths(shape))


def _put(
    container: FakeContainer,
    shape: PartitionKeyShape,
    ref: str,
    *,
    customer: str = "contoso",
    doc_type: str = "entity",
    created: str = "2026-01-01T00:00:00Z",
) -> str:
    doc = make_doc(
        shape,
        doc_type,  # type: ignore[arg-type]
        ref,
        {"created_at": created},
        cloud="commercial",
        customer_id=customer,
        domain_id=DOMAIN,
    )
    container.docs[(container._pk_of(doc), doc["id"])] = doc  # pyright: ignore[reportPrivateUsage]
    return str(doc["id"])


@pytest.fixture(params=SHAPES, ids=[s.value for s in SHAPES])
def shape(request: pytest.FixtureRequest) -> PartitionKeyShape:
    return request.param


def _backend(container: FakeContainer, shape: PartitionKeyShape) -> CatalogLifecycleBackend:
    return CatalogLifecycleBackend(
        container, shape=shape, cloud="commercial", customer_id="contoso"
    )


async def test_read_remove_then_read_back_absent(shape: PartitionKeyShape) -> None:
    container = _container(shape)
    doc_id = _put(container, shape, "commercial:contoso:src:agent:a1")
    backend = _backend(container, shape)
    found = await backend.read(doc_id)
    assert found is not None
    assert found["data_class"] == "catalog_entity"
    assert found["created_at"].year == 2026
    await backend.remove(doc_id)
    assert await backend.read(doc_id) is None
    assert container.docs == {}


async def test_missing_record_is_a_no_op(shape: PartitionKeyShape) -> None:
    backend = _backend(_container(shape), shape)
    assert await backend.read("entity:nope") is None
    await backend.remove("entity:nope")


async def test_other_customers_documents_are_invisible_and_survive(
    shape: PartitionKeyShape,
) -> None:
    container = _container(shape)
    theirs = _put(container, shape, "commercial:fabrikam:src:agent:a1", customer="fabrikam")
    backend = _backend(container, shape)
    assert await backend.read(theirs) is None
    await backend.remove(theirs)
    assert len(container.docs) == 1
    assert await backend.page("catalog_entity", 10, None) == []


async def test_page_filters_by_data_class_and_pages_after_cursor(shape: PartitionKeyShape) -> None:
    container = _container(shape)
    ids = sorted(_put(container, shape, f"commercial:contoso:src:agent:a{i}") for i in range(3))
    _put(container, shape, "commercial:contoso:src:agent:e1", doc_type="edge")
    backend = _backend(container, shape)
    first = await backend.page("catalog_entity", 2, None)
    assert [d["id"] for d in first] == ids[:2]
    rest = await backend.page("catalog_entity", 2, ids[1])
    assert [d["id"] for d in rest] == ids[2:]
    assert len(await backend.page("catalog_edge", 10, None)) == 1
    assert await backend.page("something_else", 10, None) == []
    assert await backend.page("catalog_bogus", 10, None) == []


async def test_subject_and_pseudonymize_are_honest(shape: PartitionKeyShape) -> None:
    container = _container(shape)
    doc_id = _put(container, shape, "commercial:contoso:src:agent:a1")
    backend = _backend(container, shape)
    assert await backend.page_by_subject("anyone", 10, None) == []
    with pytest.raises(CapabilityUnavailableError):
        await backend.redact_subject(doc_id)
    exported = await backend.project(doc_id)
    assert exported["id"] == doc_id
    assert "body" not in exported


def test_audit_container_is_refused(shape: PartitionKeyShape) -> None:
    backend = _backend(_container(shape), shape)
    for name in ("audit", "audit_tail"):
        with pytest.raises(ValueError):
            catalog_target(name, backend)
    assert catalog_target("catalog", backend).target_kind == "catalog"


async def test_engine_deletes_through_the_catalog_target(shape: PartitionKeyShape) -> None:
    container = _container(shape)
    doc_id = _put(container, shape, "commercial:contoso:src:agent:a1")
    rig = make_rig(
        mode="execute",
        state=load_policy(policy_for("catalog_entity")),
        target=catalog_target("catalog", _backend(container, shape)),  # type: ignore[arg-type]
    )
    request = LifecycleRequest(
        action=ActionKind.DELETE,
        target=TargetRef(target_kind="catalog", container="catalog", record_id=doc_id),
    )
    out = await rig.engine.submit(request, make_ctx())
    assert (out.status, out.effect, out.verified) == (JobStatus.COMPLETED, Effect.DELETED, True)
    assert container.docs == {}
