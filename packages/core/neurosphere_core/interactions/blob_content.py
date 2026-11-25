"""Encrypted interaction content in blob storage, one envelope per interaction (PRP-102 item 4).

Blob name: ``{customer_id}/{domain}/{yyyy}/{mm}/{dd}/{interaction_id}.env`` where the date is the
interaction's ``captured_at`` (UTC) and ``{domain}`` is the canonical domain id with ``/`` and
``%`` percent-encoded (a domain id may contain ``/``, which would otherwise add path segments).
Names are built and parsed strictly (the ``lifecycle/archive_backend.py`` style): anything that
is not exactly such a name is refused, never normalised.

The container client is injected (``azure.storage.blob.aio.ContainerClient`` or a fake), as the
archive and quarantine stores do. The container is created on first write only when
``NS_ENV=local`` (Azurite); everywhere else a missing container is ``content_container_missing``
and is never created here (PRP-109 provisions it). Writes are create-only. SDK errors are mapped
to reason codes ``from None``; no URL, name or byte of content reaches a message.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Final, Protocol, runtime_checkable
from urllib.parse import quote, unquote

from azure.core.exceptions import ResourceExistsError, ResourceNotFoundError

from neurosphere_core.cloud import Settings, load_settings
from neurosphere_core.interactions.models import (
    CONTENT_CONTAINER_MISSING,
    INTERACTION_EXISTS,
    INTERACTION_STORE_UNAVAILABLE,
    InteractionStoreError,
)

__all__ = [
    "BLOB_SUFFIX",
    "BlobInteractionContent",
    "ContentBackend",
    "ContentBlobName",
    "ContentContainer",
    "InMemoryInteractionContent",
    "content_blob_name",
    "parse_content_blob_name",
]

BLOB_SUFFIX: Final = ".env"
_CUSTOMER: Final = re.compile(r"^[a-z0-9._-]{1,128}$")
_DOMAIN: Final = re.compile(
    r"^(commercial|government):[a-z0-9._-]+:[a-z0-9._-]+:domain:[a-z0-9._/=-]+$"
)
_UUID: Final = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
_NAME: Final = re.compile(
    r"^(?P<customer>[a-z0-9._-]{1,128})/(?P<domain>[a-z0-9._:=%A-F-]{1,1536})/"
    r"(?P<y>\d{4})/(?P<m>\d{2})/(?P<d>\d{2})/"
    r"(?P<iid>[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})"
    + re.escape(BLOB_SUFFIX)
    + "$"
)
_DOMAIN_SAFE: Final = ":=._-"
_MAX_DOMAIN: Final = 512


@dataclass(frozen=True, slots=True)
class ContentBlobName:
    customer_id: str
    domain_id: str
    year: int
    month: int
    day: int
    interaction_id: str


def _bad_name() -> ValueError:
    return ValueError("not an interaction content blob name")


def content_blob_name(
    customer_id: str, domain_id: str, captured_at: datetime, interaction_id: str
) -> str:
    """The one blob name for an interaction; ``ValueError`` when any part is not well-formed."""
    if not _CUSTOMER.fullmatch(customer_id) or customer_id in {".", ".."}:
        raise _bad_name()
    if len(domain_id) > _MAX_DOMAIN or not _DOMAIN.fullmatch(domain_id):
        raise _bad_name()
    if not _UUID.fullmatch(interaction_id):
        raise _bad_name()
    if captured_at.tzinfo is None:
        raise _bad_name()
    day = captured_at.astimezone(UTC)
    domain = quote(domain_id, safe=_DOMAIN_SAFE)
    return (
        f"{customer_id}/{domain}/{day.year:04d}/{day.month:02d}/{day.day:02d}/"
        f"{interaction_id}{BLOB_SUFFIX}"
    )


def parse_content_blob_name(name: object) -> ContentBlobName | None:
    """Strict inverse of :func:`content_blob_name`; ``None`` for anything else."""
    if not isinstance(name, str):
        return None
    match = _NAME.fullmatch(name)
    if match is None or match["customer"] in {".", ".."}:
        return None
    domain_id = unquote(match["domain"])
    if (
        len(domain_id) > _MAX_DOMAIN
        or not _DOMAIN.fullmatch(domain_id)
        or quote(domain_id, safe=_DOMAIN_SAFE) != match["domain"]
    ):
        return None
    try:
        datetime(int(match["y"]), int(match["m"]), int(match["d"]), tzinfo=UTC)
    except ValueError:
        return None
    return ContentBlobName(
        customer_id=match["customer"],
        domain_id=domain_id,
        year=int(match["y"]),
        month=int(match["m"]),
        day=int(match["d"]),
        interaction_id=match["iid"],
    )


def _checked(name: str) -> str:
    if parse_content_blob_name(name) is None:
        raise _bad_name()
    return name


@runtime_checkable
class ContentBackend(Protocol):
    """Where sealed envelopes rest. Names are always :func:`content_blob_name` names."""

    async def put(self, name: str, data: bytes) -> None:
        """Create-only; an existing blob is ``interaction_exists`` and is left untouched."""
        ...

    async def get(self, name: str) -> bytes | None:
        """The stored bytes, or ``None`` when the blob does not exist."""
        ...

    async def delete(self, name: str) -> bool:
        """Idempotent; ``True`` when a blob was removed, ``False`` when there was none."""
        ...


class InMemoryInteractionContent:
    """In-memory :class:`ContentBackend` with the same name rules and create-only semantics."""

    def __init__(self) -> None:
        self.blobs: dict[str, bytes] = {}

    async def put(self, name: str, data: bytes) -> None:
        _checked(name)
        if not isinstance(data, bytes):
            raise TypeError("content backends store envelope bytes only")
        if name in self.blobs:
            raise InteractionStoreError(INTERACTION_EXISTS)
        self.blobs[name] = data

    async def get(self, name: str) -> bytes | None:
        _checked(name)
        return self.blobs.get(name)

    async def delete(self, name: str) -> bool:
        _checked(name)
        return self.blobs.pop(name, None) is not None


class _Download(Protocol):
    async def readall(self) -> bytes: ...


class ContentContainer(Protocol):
    """The slice of ``azure.storage.blob.aio.ContainerClient`` this backend uses."""

    async def upload_blob(
        self, name: str, data: bytes, *, overwrite: bool = False, **kwargs: Any
    ) -> Any: ...

    async def download_blob(self, blob: str, **kwargs: Any) -> _Download: ...

    async def delete_blob(self, blob: str, **kwargs: Any) -> None: ...

    async def create_container(self, **kwargs: Any) -> Any: ...


def _error_code(exc: Exception) -> str | None:
    code = getattr(exc, "error_code", None)
    return str(code) if code is not None else None


def _container_missing(exc: Exception) -> bool:
    return _error_code(exc) == "ContainerNotFound"


class BlobInteractionContent:
    """:class:`ContentBackend` over one blob container (async azure-storage-blob)."""

    def __init__(self, container: ContentContainer, *, settings: Settings | None = None) -> None:
        self._container = container
        self._settings = settings
        self._ready = False

    def _local(self) -> bool:
        try:
            settings = self._settings or load_settings()
        except Exception:
            return False  # an unreadable environment is not local
        return settings.env == "local"

    async def _ensure_container(self) -> None:
        """Create the container under ``NS_ENV=local`` only; elsewhere it must already exist."""
        if self._ready or not self._local():
            return
        try:
            await self._container.create_container()
        except ResourceExistsError:
            pass
        except Exception:
            raise InteractionStoreError(INTERACTION_STORE_UNAVAILABLE) from None
        self._ready = True

    async def put(self, name: str, data: bytes) -> None:
        _checked(name)
        if not isinstance(data, bytes):
            raise TypeError("content backends store envelope bytes only")
        await self._ensure_container()
        try:
            await self._container.upload_blob(name, data, overwrite=False)
        except ResourceExistsError:
            raise InteractionStoreError(INTERACTION_EXISTS) from None
        except ResourceNotFoundError as exc:
            reason = (
                CONTENT_CONTAINER_MISSING
                if _container_missing(exc)
                else INTERACTION_STORE_UNAVAILABLE
            )
            raise InteractionStoreError(reason) from None
        except Exception:
            raise InteractionStoreError(INTERACTION_STORE_UNAVAILABLE) from None

    async def get(self, name: str) -> bytes | None:
        _checked(name)
        try:
            download = await self._container.download_blob(name)
            data = await download.readall()
        except ResourceNotFoundError as exc:
            if _container_missing(exc) and not self._local():
                raise InteractionStoreError(CONTENT_CONTAINER_MISSING) from None
            return None
        except Exception:
            raise InteractionStoreError(INTERACTION_STORE_UNAVAILABLE) from None
        return bytes(data)

    async def delete(self, name: str) -> bool:
        _checked(name)
        try:
            await self._container.delete_blob(name)
        except ResourceNotFoundError as exc:
            if _container_missing(exc) and not self._local():
                raise InteractionStoreError(CONTENT_CONTAINER_MISSING) from None
            return False
        except Exception:
            raise InteractionStoreError(INTERACTION_STORE_UNAVAILABLE) from None
        return True
