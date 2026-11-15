"""Store-backed producer registry layered over the producers file (PRP-41 item 2).

``ProducerRegistry.get`` is synchronous and runs on the request path, so the store layer serves
an immutable snapshot that a background task refreshes from the ``admin_config`` store every
``NS_INGEST_PRODUCER_REFRESH_SECONDS`` (default 30), plus an immediate local update after every
admin write. Other replicas see a change within one refresh interval.

Rules (PRP-41 acceptance):

* the store record wins over a file entry with the same ``producer_id``; a DISABLED store record
  hides the file entry too (the id is refused, never falls back);
* a refresh failure keeps the last snapshot, records a reason code and never raises into a
  request; before the first successful refresh the snapshot is empty, so store-only producers
  fail closed (401) while file producers keep authenticating;
* nothing here logs or stores a secret: records carry only the SHA-256 digest.

``NS_INGEST_PRODUCER_STORE`` (default false) turns the layer on; off, ingest is exactly the
static file registry.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Awaitable, Callable, Mapping, Sequence
from types import MappingProxyType
from typing import Final

from neurosphere_contracts.admin.v1.admin_config_document import AdminConfigDocument
from neurosphere_contracts.admin.v1.producer_record import ProducerRecord
from neurosphere_core.admin.producers import registration_from_record
from pydantic import Field, ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict

from neurosphere_api.ingest.auth import ProducerRegistration, ProducerRegistry

__all__ = [
    "REASON_RECORD_INVALID",
    "REASON_STORE_UNAVAILABLE",
    "LayeredProducerRegistry",
    "ProducerStoreSettings",
    "StoreProducerRegistry",
    "run_refresher",
]

REASON_STORE_UNAVAILABLE: Final = "producer_store_unavailable"
REASON_RECORD_INVALID: Final = "producer_record_invalid"
_log = logging.getLogger("neurosphere_api.ingest")

Loader = Callable[[], Awaitable[Sequence[AdminConfigDocument]]]


class ProducerStoreSettings(BaseSettings):
    """``NS_INGEST_PRODUCER_STORE`` and ``NS_INGEST_PRODUCER_REFRESH_SECONDS``."""

    model_config = SettingsConfigDict(env_prefix="NS_INGEST_PRODUCER_", frozen=True, extra="ignore")

    store: bool = False
    refresh_seconds: float = Field(default=30.0, gt=0, le=3600)


def _registration(document: AdminConfigDocument) -> tuple[str, ProducerRegistration | None] | None:
    """``(producer_id, registration)``; ``None`` registration marks a disabled/retired record."""
    body = document.body
    if not isinstance(body, ProducerRecord):
        return None
    if document.status != "active" or body.status != "active":
        return body.producer_id, None
    try:
        return body.producer_id, ProducerRegistration.model_validate(registration_from_record(body))
    except ValidationError:
        return body.producer_id, None  # an unusable record fails closed


class StoreProducerRegistry:
    """Immutable-snapshot registry; ``get`` never blocks and never raises."""

    def __init__(self) -> None:
        self._snapshot: Mapping[str, ProducerRegistration | None] = MappingProxyType({})
        #: Last refresh outcome: ``None`` when healthy, else a reason code (never a message).
        self.last_reason: str | None = None

    def knows(self, producer_id: str) -> bool:
        """True when the store has a record (active or disabled) for the id."""
        return producer_id in self._snapshot

    def get(self, producer_id: str) -> ProducerRegistration | None:
        return self._snapshot.get(producer_id)

    def apply(self, document: AdminConfigDocument) -> None:
        """Immediate local update after an admin write (copy-on-write)."""
        entry = _registration(document)
        if entry is None:
            return
        updated = dict(self._snapshot)
        updated[entry[0]] = entry[1]
        self._snapshot = MappingProxyType(updated)

    def invalidate(self, producer_id: str) -> None:
        """Drop the id from the snapshot (it fails closed until the next refresh)."""
        if producer_id in self._snapshot:
            updated = {k: v for k, v in self._snapshot.items() if k != producer_id}
            self._snapshot = MappingProxyType(updated)

    async def refresh(self, loader: Loader) -> bool:
        """Replace the snapshot from the store. True on success; on failure keep the old one."""
        try:
            documents = await loader()
        except Exception:
            self.last_reason = REASON_STORE_UNAVAILABLE
            return False
        snapshot: dict[str, ProducerRegistration | None] = {}
        bad = False
        for document in documents:
            entry = _registration(document)
            if entry is None:
                bad = True
                continue
            snapshot[entry[0]] = entry[1]
        self._snapshot = MappingProxyType(snapshot)
        self.last_reason = REASON_RECORD_INVALID if bad else None
        return True


class LayeredProducerRegistry:
    """Store first, file fallback. Same sync ``ProducerRegistry`` protocol the edge uses."""

    def __init__(self, store: StoreProducerRegistry, fallback: ProducerRegistry) -> None:
        self.store = store
        self._fallback = fallback

    def get(self, producer_id: str) -> ProducerRegistration | None:
        if self.store.knows(producer_id):
            return self.store.get(producer_id)
        return self._fallback.get(producer_id)


async def run_refresher(store: StoreProducerRegistry, loader: Loader, interval: float) -> None:
    """Refresh forever; cancelled by the composition lifetime at shutdown."""
    while True:
        await store.refresh(loader)
        if store.last_reason is not None:
            _log.warning("producer store refresh: %s", store.last_reason)
        await asyncio.sleep(interval)


async def stop_refresher(task: asyncio.Task[None]) -> None:
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task
