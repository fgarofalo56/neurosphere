"""The minimal slice of ``azure.storage.blob.aio.ContainerClient`` the archive uses."""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable
from typing import Any, Protocol


class BlobItem(Protocol):
    """A listed blob (``BlobProperties`` in the SDK). Needs ``include=["metadata"]``."""

    @property
    def name(self) -> str: ...

    @property
    def metadata(self) -> dict[str, str] | None: ...


class BlobContainer(Protocol):
    """Injected container client. The real one is a ``ContainerClient``.

    ``upload_blob(..., overwrite=False)`` MUST raise ``azure.core.exceptions.ResourceExistsError``
    when the blob already exists (the SDK does).
    """

    def upload_blob(
        self,
        name: str,
        data: bytes,
        *,
        overwrite: bool = False,
        metadata: dict[str, str] | None = None,
        **kwargs: Any,
    ) -> Awaitable[Any]: ...

    def list_blobs(
        self,
        name_starts_with: str | None = None,
        *,
        include: list[str] | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[BlobItem]: ...
