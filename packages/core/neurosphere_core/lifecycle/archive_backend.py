"""Lifecycle ``DocumentBackend`` over the redacted-archive blob container (PRP-23 item 2).

Blob names follow the archive writer (``neurosphere_workers/archive/serialize.py``, read only):
``{customer}/{domain or _none}/{yyyy}/{mm}/{dd}/{doc_id}.json.gz`` with a ``manifest.json`` per
day. The record id is the blob name. The backend is bound to one customer prefix, accepts only
names that look exactly like archive records (never a manifest, never a path with ``..``, an
absolute path or another customer's prefix), and the audit container is never accepted.

Archive blobs are already redacted and pseudonymized at write time, so subject enumeration
answers "none" and in-place pseudonymization is reported as unsupported rather than faked.
"""

from __future__ import annotations

import re
from collections.abc import AsyncIterator, Mapping
from datetime import UTC, datetime
from typing import Any, Final, Protocol

from azure.core.exceptions import ResourceNotFoundError

from neurosphere_core.errors import (
    CapabilityUnavailableError,
    DependencyTransientError,
    NeuroSphereError,
)
from neurosphere_core.lifecycle.adapters import ArchiveTarget
from neurosphere_core.lifecycle.rules import is_audit_container

__all__ = ["ArchiveLifecycleBackend", "archive_target"]

DATA_CLASS_ARCHIVE: Final = "archive_event"
BLOB_SUFFIX: Final = ".json.gz"
NO_DOMAIN: Final = "_none"
_NAME: Final = re.compile(
    r"^(?P<customer>[^/\\\x00-\x1f]+)/(?P<domain>[^/\\\x00-\x1f]+)/"
    r"(?P<y>\d{4})/(?P<m>\d{2})/(?P<d>\d{2})/(?P<doc>[^/\\\x00-\x1f]+)"
    + re.escape(BLOB_SUFFIX)
    + "$"
)


class _BlobItem(Protocol):
    @property
    def name(self) -> str: ...


class _BlobClient(Protocol):
    async def get_blob_properties(self) -> Any: ...

    async def delete_blob(self, **kwargs: Any) -> None: ...

    async def download_blob(self, **kwargs: Any) -> Any: ...


class ArchiveContainer(Protocol):
    """The slice of ``azure.storage.blob.aio.ContainerClient`` this backend uses."""

    def list_blobs(
        self, name_starts_with: str | None = None, **kwargs: Any
    ) -> AsyncIterator[_BlobItem]: ...

    def get_blob_client(self, blob: str, *args: Any, **kwargs: Any) -> Any: ...


def _unavailable(exc: Exception) -> Exception:
    if isinstance(exc, NeuroSphereError):
        return exc
    return DependencyTransientError("archive store unavailable", reason="archive_store_unavailable")


class ArchiveLifecycleBackend:
    """:class:`~neurosphere_core.lifecycle.adapters.DocumentBackend` for one customer's archive."""

    def __init__(self, container: ArchiveContainer, *, customer_id: str) -> None:
        if not customer_id or "/" in customer_id or "\\" in customer_id:
            raise ValueError("customer_id is not usable as an archive path segment")
        self._container = container
        self._customer = customer_id

    def _parse(self, record_id: str) -> re.Match[str] | None:
        match = _NAME.match(record_id)
        if match is None or match["customer"] != self._customer:
            return None
        if ".." in {match["domain"], match["doc"]} or match["doc"] in {".", ".."}:
            return None
        return match

    def _mapping(self, record_id: str, match: re.Match[str]) -> dict[str, Any]:
        try:
            created = datetime(int(match["y"]), int(match["m"]), int(match["d"]), tzinfo=UTC)
        except ValueError:
            created = datetime.now(UTC)  # an impossible date never looks older than it is
        domain = match["domain"]
        return {
            "id": record_id,
            "data_class": DATA_CLASS_ARCHIVE,
            "created_at": created,
            "doc_type": "archive_blob",
            "customer_id": match["customer"],
            "domain_id": None if domain == NO_DOMAIN else domain,
        }

    async def _exists(self, record_id: str) -> bool:
        try:
            await self._container.get_blob_client(record_id).get_blob_properties()
        except ResourceNotFoundError:
            return False
        except Exception as exc:
            raise _unavailable(exc) from exc
        return True

    async def read(self, record_id: str) -> Mapping[str, Any] | None:
        match = self._parse(record_id)
        if match is None or not await self._exists(record_id):
            return None
        return self._mapping(record_id, match)

    async def remove(self, record_id: str) -> None:
        if self._parse(record_id) is None:
            return  # not an archive record of this customer: never delete it
        try:
            await self._container.get_blob_client(record_id).delete_blob()
        except ResourceNotFoundError:
            return
        except Exception as exc:
            raise _unavailable(exc) from exc

    async def page(self, data_class: str, limit: int, after: str | None) -> list[Mapping[str, Any]]:
        if data_class != DATA_CLASS_ARCHIVE:
            return []
        out: list[Mapping[str, Any]] = []
        try:
            async for item in self._container.list_blobs(name_starts_with=f"{self._customer}/"):
                name = item.name
                if after is not None and name <= after:
                    continue
                match = self._parse(name)
                if match is None:
                    continue  # a manifest or anything that is not an archive record
                out.append(self._mapping(name, match))
        except Exception as exc:
            raise _unavailable(exc) from exc
        out.sort(key=lambda d: str(d["id"]))
        return out[: max(1, limit)]

    async def page_by_subject(
        self, subject_id: str, limit: int, after: str | None
    ) -> list[Mapping[str, Any]]:
        # Archive records are redacted and pseudonymized when written: nothing to enumerate.
        return []

    async def redact_subject(self, record_id: str) -> None:
        raise CapabilityUnavailableError("pseudonymize_unsupported")

    async def project(self, record_id: str) -> Mapping[str, Any]:
        match = self._parse(record_id)
        if match is None or not await self._exists(record_id):
            return {}
        # Metadata only; the compressed record body is not exported through this path.
        return {k: v for k, v in self._mapping(record_id, match).items() if k != "created_at"}


def archive_target(container_name: str, backend: ArchiveLifecycleBackend) -> ArchiveTarget:
    """The registry-ready target. Refuses the audit container by name."""
    if is_audit_container(container_name):
        raise ValueError("the audit container cannot be a lifecycle target")
    return ArchiveTarget(container_name, backend)
