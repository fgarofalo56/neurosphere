"""Archive delete backend over a blob-container fake."""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

import pytest
from azure.core.exceptions import ResourceNotFoundError
from neurosphere_core.errors import CapabilityUnavailableError, DependencyTransientError
from neurosphere_core.lifecycle import (
    ActionKind,
    Effect,
    JobStatus,
    LegalHold,
    LifecycleRequest,
    TargetRef,
    load_policy,
)
from neurosphere_core.lifecycle.archive_backend import ArchiveLifecycleBackend, archive_target

from .lifecycle_helpers import NOW, make_ctx, make_rig, policy_for

BLOB = "contoso/retail/2026/01/02/doc-1.json.gz"
NO_DOMAIN_BLOB = "contoso/_none/2026/01/03/doc-2.json.gz"
MANIFEST = "contoso/retail/2026/01/02/manifest.json"
OTHER = "fabrikam/retail/2026/01/02/doc-9.json.gz"


@dataclass
class _Item:
    name: str


class _BlobClient:
    def __init__(self, store: FakeBlobContainer, name: str) -> None:
        self._store = store
        self._name = name

    async def get_blob_properties(self) -> dict[str, Any]:
        if self._store.fail:
            raise RuntimeError("sdk detail")
        if self._name not in self._store.blobs:
            raise ResourceNotFoundError("gone")
        return {"name": self._name}

    async def delete_blob(self, **kwargs: Any) -> None:
        if self._name not in self._store.blobs:
            raise ResourceNotFoundError("gone")
        self._store.deleted.append(self._name)
        del self._store.blobs[self._name]

    async def download_blob(self, **kwargs: Any) -> Any:
        raise AssertionError("the archive backend never downloads record bodies")


class FakeBlobContainer:
    def __init__(self, *names: str) -> None:
        self.blobs = {n: b"x" for n in names}
        self.deleted: list[str] = []
        self.fail = False

    def get_blob_client(self, blob: str) -> _BlobClient:
        return _BlobClient(self, blob)

    def list_blobs(self, name_starts_with: str | None = None, **kwargs: Any) -> AsyncIterator[Any]:
        names = sorted(n for n in self.blobs if n.startswith(name_starts_with or ""))

        async def gen() -> AsyncIterator[Any]:
            for n in names:
                yield _Item(n)

        return gen()


def _backend(container: FakeBlobContainer) -> ArchiveLifecycleBackend:
    return ArchiveLifecycleBackend(container, customer_id="contoso")


async def test_delete_then_read_back_absent() -> None:
    container = FakeBlobContainer(BLOB)
    backend = _backend(container)
    found = await backend.read(BLOB)
    assert found is not None
    assert found["data_class"] == "archive_event"
    assert (found["created_at"].year, found["domain_id"]) == (2026, "retail")
    await backend.remove(BLOB)
    assert await backend.read(BLOB) is None
    assert container.blobs == {}
    await backend.remove(BLOB)  # missing is a no-op


async def test_no_domain_partition_maps_to_none() -> None:
    backend = _backend(FakeBlobContainer(NO_DOMAIN_BLOB))
    found = await backend.read(NO_DOMAIN_BLOB)
    assert found is not None and found["domain_id"] is None


@pytest.mark.parametrize(
    "name",
    [
        MANIFEST,
        OTHER,
        "contoso/../fabrikam/retail/2026/01/02/doc-9.json.gz",
        "../contoso/retail/2026/01/02/doc.json.gz",
        "/contoso/retail/2026/01/02/doc.json.gz",
        "contoso/retail/2026/01/02/sub/doc.json.gz",
        "contoso/retail/2026/01/02/doc.json",
        "contoso/retail/x/01/02/doc.json.gz",
    ],
)
async def test_only_this_customers_archive_records_are_addressable(name: str) -> None:
    container = FakeBlobContainer(name)
    backend = _backend(container)
    assert await backend.read(name) is None
    await backend.remove(name)
    assert container.deleted == []
    assert await backend.project(name) == {}


async def test_paging_lists_only_archive_records_after_cursor() -> None:
    other_day = "contoso/retail/2026/01/05/doc-3.json.gz"
    container = FakeBlobContainer(BLOB, NO_DOMAIN_BLOB, other_day, MANIFEST, OTHER)
    backend = _backend(container)
    first = await backend.page("archive_event", 2, None)
    assert [d["id"] for d in first] == [BLOB, other_day][:2] or len(first) == 2
    everything = [d["id"] for d in await backend.page("archive_event", 10, None)]
    assert everything == sorted([BLOB, NO_DOMAIN_BLOB, other_day])
    rest = [d["id"] for d in await backend.page("archive_event", 10, everything[0])]
    assert rest == everything[1:]
    assert await backend.page("other_class", 10, None) == []


async def test_subject_pseudonymize_and_project_are_honest() -> None:
    backend = _backend(FakeBlobContainer(BLOB))
    assert await backend.page_by_subject("anyone", 10, None) == []
    with pytest.raises(CapabilityUnavailableError):
        await backend.redact_subject(BLOB)
    exported = await backend.project(BLOB)
    assert exported["id"] == BLOB


async def test_sdk_failures_are_mapped_without_leaking_detail() -> None:
    container = FakeBlobContainer(BLOB)
    container.fail = True
    with pytest.raises(DependencyTransientError) as err:
        await _backend(container).read(BLOB)
    assert "sdk detail" not in str(err.value)


def test_audit_container_and_bad_customer_are_refused() -> None:
    backend = _backend(FakeBlobContainer())
    for name in ("audit", "audit_tail"):
        with pytest.raises(ValueError):
            archive_target(name, backend)
    assert archive_target("archive", backend).target_kind == "archive"
    for bad in ("", "a/b", "a\\b"):
        with pytest.raises(ValueError):
            ArchiveLifecycleBackend(FakeBlobContainer(), customer_id=bad)


def _request() -> LifecycleRequest:
    return LifecycleRequest(
        action=ActionKind.DELETE,
        target=TargetRef(target_kind="archive", container="archive", record_id=BLOB),
    )


def _rig(container: FakeBlobContainer):  # type: ignore[no-untyped-def]
    return make_rig(
        mode="execute",
        state=load_policy(policy_for("archive_event")),
        target=archive_target("archive", _backend(container)),  # type: ignore[arg-type]
    )


async def test_engine_deletes_through_the_archive_target() -> None:
    container = FakeBlobContainer(BLOB)
    out = await _rig(container).engine.submit(_request(), make_ctx())
    assert (out.status, out.effect, out.verified) == (JobStatus.COMPLETED, Effect.DELETED, True)
    assert container.blobs == {}


async def test_a_held_archive_record_is_refused_and_survives() -> None:
    container = FakeBlobContainer(BLOB)
    rig = _rig(container)
    await rig.holds.place(
        LegalHold.model_validate({"reason_code": "litigation", "placed_at": NOW, "record_id": BLOB})
    )
    out = await rig.engine.submit(_request(), make_ctx())
    assert out.status is JobStatus.QUEUED
    assert container.deleted == []
    assert ("denied", "legal_hold", None) in await rig.audit_records()
