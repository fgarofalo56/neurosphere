"""Blob-storage access for Cost Management exports via ``azure-storage-blob`` (async).

Uses only ``ContainerClient(account_url, container_name, credential=...)``,
``get_blob_client(blob).download_blob().readall()`` from the documented client library
(https://learn.microsoft.com/python/api/azure-storage-blob/). The export writes
``manifest.json`` next to its partitions; ``manifest_blob`` is the operator-supplied full blob
path of that file (the export's ``rootFolderPath``/``exportName``/run folder), so no path is
guessed. The credential is injected (async token credential); none is created here, and no
network is touched until a read is called.
"""

from __future__ import annotations

import importlib
from typing import Any

from neurosphere_core.errors import (
    DependencyTransientError,
    ForbiddenError,
    NeuroSphereError,
    RateLimitedError,
    UnauthorizedError,
)

__all__ = ["AzureBlobExportSource"]


def _map(exc: Exception) -> NeuroSphereError:
    if isinstance(exc, NeuroSphereError):
        return exc
    status = getattr(exc, "status_code", None)
    if status == 429:
        return RateLimitedError(retry_after_seconds=30)
    if status == 401:
        return UnauthorizedError()
    if status == 403:
        return ForbiddenError()
    return DependencyTransientError()


class AzureBlobExportSource:
    """``ExportBlobSource`` over one storage container."""

    def __init__(
        self,
        *,
        account_url: str,
        container: str,
        manifest_blob: str,
        credential: Any,
    ) -> None:
        module = importlib.import_module("azure.storage.blob.aio")
        self._container: Any = module.ContainerClient(account_url, container, credential=credential)
        self._manifest_blob = manifest_blob

    async def _download(self, name: str) -> bytes:
        try:
            stream = await self._container.get_blob_client(name).download_blob()
            data = await stream.readall()
        except Exception as exc:
            raise _map(exc) from None
        return bytes(data)

    async def read_manifest(self) -> bytes:
        return await self._download(self._manifest_blob)

    async def read_blob(self, name: str) -> bytes:
        return await self._download(name)

    async def close(self) -> None:
        await self._container.close()
