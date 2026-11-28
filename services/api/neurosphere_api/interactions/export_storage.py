"""Where interaction exports rest (PRP-104 item 4): ``exports/`` in the content container.

PRP-102 stores sealed interaction content in one blob container and defines no export prefix;
this module adds one. Every export is two blobs::

    exports/{customer_id}/{domain}/{export_id}/manifest.json   InteractionExportManifest (JSON)
    exports/{customer_id}/{domain}/{export_id}/bundle.env      PRP-102 envelope of the bundle

``{domain}`` is the canonical domain id with ``/`` and ``%`` percent-encoded (as in PRP-102's
content blob names). The manifest is metadata only (ids, counts, purpose, the bundle reference);
the bundle is sealed. Export state (which exports are open, who made them, when they expire)
is derived from the manifests under ``exports/{customer_id}/``: no index container is added.

:class:`InteractionExportStorage` is what the explorer holder carries (``exports``): the backend,
the content key wrapper and its key identifier, shared with the interaction store by the
interactions builder (``interaction_content_storage``). The module imports nothing from the rest
of the package (the explorer holder imports it).
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any, Final, Protocol, runtime_checkable
from urllib.parse import quote

from azure.core.exceptions import ResourceExistsError, ResourceNotFoundError
from neurosphere_core.crypto import KeyWrapper
from neurosphere_core.errors import DependencyTransientError

__all__ = [
    "BUNDLE_BLOB",
    "EXPORT_ROOT",
    "EXPORT_STORAGE_UNAVAILABLE",
    "MANIFEST_BLOB",
    "BlobExportBackend",
    "ExportBackend",
    "InMemoryExportBackend",
    "InteractionExportStorage",
    "export_customer_prefix",
    "export_prefix",
]

EXPORT_ROOT: Final = "exports"
MANIFEST_BLOB: Final = "manifest.json"
BUNDLE_BLOB: Final = "bundle.env"
#: 503 reason of any export blob failure (outage, missing container).
EXPORT_STORAGE_UNAVAILABLE: Final = "interaction_export_storage_unavailable"

_CUSTOMER: Final = re.compile(r"^[a-z0-9._-]{1,128}$")
_UUID: Final = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
_DOMAIN_SAFE: Final = ":=._-"
_LEAVES: Final = frozenset({MANIFEST_BLOB, BUNDLE_BLOB})


def _unavailable() -> DependencyTransientError:
    return DependencyTransientError(
        "the export storage is unavailable", reason=EXPORT_STORAGE_UNAVAILABLE
    )


def export_customer_prefix(customer_id: str) -> str:
    """``exports/{customer_id}/``; ``ValueError`` for a malformed customer."""
    if not _CUSTOMER.fullmatch(customer_id) or customer_id in {".", ".."}:
        raise ValueError("not a customer id")
    return f"{EXPORT_ROOT}/{customer_id}/"


def export_prefix(customer_id: str, domain_id: str, export_id: str) -> str:
    """``exports/{customer_id}/{domain}/{export_id}/``; ``ValueError`` when a part is malformed."""
    if not _UUID.fullmatch(export_id) or not domain_id or len(domain_id) > 512:
        raise ValueError("not an export id")
    return (
        f"{export_customer_prefix(customer_id)}{quote(domain_id, safe=_DOMAIN_SAFE)}/{export_id}/"
    )


def _checked(name: str) -> str:
    """Only names under ``exports/`` ending in a known leaf: never PRP-102 content names."""
    parts = name.split("/")
    if (
        len(parts) != 5
        or parts[0] != EXPORT_ROOT
        or not _CUSTOMER.fullmatch(parts[1])
        or not parts[2]
        or not _UUID.fullmatch(parts[3])
        or parts[4] not in _LEAVES
    ):
        raise ValueError("not an export blob name")
    return name


@runtime_checkable
class ExportBackend(Protocol):
    """Export blobs. Every failure is 503 ``interaction_export_storage_unavailable``."""

    async def put(self, name: str, data: bytes) -> None:
        """Create-only."""
        ...

    async def get(self, name: str) -> bytes | None:
        """The bytes, or ``None`` when absent."""
        ...

    async def delete(self, name: str) -> bool:
        """Idempotent; ``True`` when a blob was removed."""
        ...

    def list_names(self, prefix: str) -> AsyncIterator[str]:
        """Names under ``prefix`` (an :func:`export_customer_prefix` or deeper)."""
        ...


class InMemoryExportBackend:
    """In-memory :class:`ExportBackend` (tests, local without storage) with the same rules."""

    def __init__(self) -> None:
        self.blobs: dict[str, bytes] = {}

    async def put(self, name: str, data: bytes) -> None:
        _checked(name)
        if name in self.blobs:
            raise _unavailable()
        self.blobs[name] = bytes(data)

    async def get(self, name: str) -> bytes | None:
        return self.blobs.get(_checked(name))

    async def delete(self, name: str) -> bool:
        return self.blobs.pop(_checked(name), None) is not None

    async def list_names(self, prefix: str) -> AsyncIterator[str]:
        if not prefix.startswith(f"{EXPORT_ROOT}/"):
            raise ValueError("not an export prefix")
        for name in sorted(self.blobs):
            if name.startswith(prefix):
                yield name


class _Download(Protocol):
    async def readall(self) -> bytes: ...


class ExportContainer(Protocol):
    """The slice of ``azure.storage.blob.aio.ContainerClient`` the export backend uses."""

    async def upload_blob(
        self, name: str, data: bytes, *, overwrite: bool = False, **kwargs: Any
    ) -> Any: ...

    async def download_blob(self, blob: str, **kwargs: Any) -> _Download: ...

    async def delete_blob(self, blob: str, **kwargs: Any) -> None: ...

    async def create_container(self, **kwargs: Any) -> Any: ...

    def list_blobs(self, name_starts_with: str | None = None, **kwargs: Any) -> Any: ...


class BlobExportBackend:
    """:class:`ExportBackend` over the content container (shared with PRP-102's store).

    The container is created on first write only under ``NS_ENV=local`` (Azurite), as PRP-102's
    content backend does; elsewhere it must exist. SDK errors become reason codes ``from None``.
    """

    def __init__(self, container: ExportContainer, *, local: bool) -> None:
        self._container = container
        self._local = local
        self._ready = False

    async def _ensure_container(self) -> None:
        if self._ready or not self._local:
            return
        try:
            await self._container.create_container()
        except ResourceExistsError:
            pass  # already there
        except Exception:
            raise _unavailable() from None
        self._ready = True

    async def put(self, name: str, data: bytes) -> None:
        _checked(name)
        await self._ensure_container()
        try:
            await self._container.upload_blob(name, data, overwrite=False)
        except Exception:
            raise _unavailable() from None

    async def get(self, name: str) -> bytes | None:
        _checked(name)
        try:
            download = await self._container.download_blob(name)
            return bytes(await download.readall())
        except ResourceNotFoundError:
            return None
        except Exception:
            raise _unavailable() from None

    async def delete(self, name: str) -> bool:
        _checked(name)
        try:
            await self._container.delete_blob(name)
        except ResourceNotFoundError:
            return False
        except Exception:
            raise _unavailable() from None
        return True

    async def list_names(self, prefix: str) -> AsyncIterator[str]:
        if not prefix.startswith(f"{EXPORT_ROOT}/"):
            raise ValueError("not an export prefix")
        try:
            async for blob in self._container.list_blobs(name_starts_with=prefix):
                name = getattr(blob, "name", None)
                if isinstance(name, str):
                    yield name
        except ResourceNotFoundError:
            return  # no container yet: no exports
        except Exception:
            raise _unavailable() from None


@dataclass(frozen=True, slots=True)
class InteractionExportStorage:
    """The explorer's export side: blobs, the content key wrapper and its key identifier.

    ``lock`` serialises export creation in this process so the open-export cap is not raced by
    concurrent requests of one replica.
    """

    backend: ExportBackend
    wrapper: KeyWrapper
    kek_uri: str
    lock: asyncio.Lock = field(default_factory=asyncio.Lock, compare=False)
