"""Redacted, pseudonymized blob archive (PRP-07 item 4).

One sink = ONE cloud and ONE storage account. An event tagged for another cloud is refused
before anything is serialized or written, so Government data can never land in a
Commercial-configured account (and vice versa).

Idempotence: the blob name is deterministic (partition + ``doc_id``) and the upload uses
``overwrite=False``; "already exists" counts as success (first write wins; the content is
deterministic anyway). Retryable storage failures surface as ``DependencyTransientError``.

``build_manifest`` is separate from ``write`` on purpose: appending to a shared manifest per
event would race between concurrent writers. Run it AFTER a partition-day has settled, e.g. once
the day has closed plus the lateness window (late events are accepted and land in their event
day), and again whenever late events are backfilled. It lists the blobs, rewrites
``manifest.json`` whole, and is safe to re-run at any time.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import date, datetime
from typing import Any, Final

from azure.core.exceptions import (
    HttpResponseError,
    ResourceExistsError,
    ServiceRequestError,
    ServiceResponseError,
)
from neurosphere_core.errors import DependencyTransientError, ForbiddenError
from pydantic import BaseModel, ConfigDict, SecretStr

from neurosphere_workers.archive.protocols import BlobContainer
from neurosphere_workers.archive.serialize import (
    BLOB_SUFFIX,
    MANIFEST_NAME,
    build_blob,
    event_domain_id,
    partition_prefix,
    utc_now,
)
from neurosphere_workers.ingestion.models import NormalizedEvent, format_timestamp

_TRANSIENT_STATUS: Final = frozenset({408, 429, 500, 502, 503, 504})


class ManifestEntry(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    doc_id: str
    sha256: str | None  # the blob's recorded content hash (None if the blob lacks the metadata)


class Manifest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    customer_id: str
    domain_id: str | None
    day: date
    count: int
    generated_at: str
    entries: tuple[ManifestEntry, ...]


def _transient(exc: Exception) -> DependencyTransientError | None:
    if isinstance(exc, (ServiceRequestError, ServiceResponseError)) or (
        isinstance(exc, HttpResponseError) and exc.status_code in _TRANSIENT_STATUS
    ):
        return DependencyTransientError("archive storage unavailable", reason="archive_storage")
    return None


class BlobArchiveSink:
    """Implements ``ArchiveSink`` over an injected async blob container client."""

    def __init__(
        self,
        container: BlobContainer,
        *,
        cloud: str,
        pseudonym_key: SecretStr,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        if cloud not in {"commercial", "government"}:
            raise ValueError("cloud must be 'commercial' or 'government'")
        self._container = container
        self._cloud = cloud
        self._key = pseudonym_key.get_secret_value().encode("utf-8")
        self._clock = clock

    @property
    def cloud(self) -> str:
        return self._cloud

    async def write(self, event: NormalizedEvent) -> None:
        if event.message.cloud != self._cloud or event.contract.cloud != self._cloud:
            raise ForbiddenError(
                "event cloud does not match the archive's configured cloud", reason="cloud_mismatch"
            )
        blob = build_blob(event, self._key)
        try:
            await self._container.upload_blob(
                blob.name, blob.data, overwrite=False, metadata={"sha256": blob.sha256}
            )
        except ResourceExistsError:
            return  # redelivery: already archived
        except Exception as exc:
            transient = _transient(exc)
            if transient is not None:
                raise transient from exc
            raise

    async def build_manifest(self, customer_id: str, domain_id: str | None, day: date) -> Manifest:
        """(Re)write ``{partition-day}/manifest.json`` from the blobs currently present."""
        prefix = partition_prefix(customer_id, domain_id, day)
        entries: list[ManifestEntry] = []
        try:
            async for item in self._container.list_blobs(prefix, include=["metadata"]):
                leaf = item.name[len(prefix) :]
                if "/" in leaf or not leaf.endswith(BLOB_SUFFIX):
                    continue  # the manifest itself, or anything not an archive record
                sha = (item.metadata or {}).get("sha256")
                entries.append(ManifestEntry(doc_id=leaf[: -len(BLOB_SUFFIX)], sha256=sha))
            entries.sort(key=lambda e: e.doc_id)
            manifest = Manifest(
                customer_id=customer_id,
                domain_id=domain_id,
                day=day,
                count=len(entries),
                generated_at=format_timestamp(self._clock()),
                entries=tuple(entries),
            )
            body: dict[str, Any] = manifest.model_dump(mode="json")
            data = json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")
            await self._container.upload_blob(f"{prefix}{MANIFEST_NAME}", data, overwrite=True)
        except Exception as exc:
            transient = _transient(exc)
            if transient is not None:
                raise transient from exc
            raise
        return manifest


def manifest_partition(event: NormalizedEvent) -> tuple[str, str | None]:
    """(customer_id, domain_id) of an event, for callers scheduling manifest builds."""
    return event.message.customer_id, event_domain_id(event)
