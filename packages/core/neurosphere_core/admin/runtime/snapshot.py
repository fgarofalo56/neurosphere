"""Immutable stored-settings snapshot, read once at startup (PRP-45, A1).

:func:`load_stored_settings` lists the ``system_setting`` documents of one customer under a bounded
timeout and re-validates every body for the deployment cloud. A document that no longer validates
(for example the deployment moved cloud) is left out and named in ``invalid``: its key falls back
to the environment. A store that times out or fails yields an EMPTY snapshot with status
``unavailable`` and reason :data:`STORED_SETTINGS_UNAVAILABLE`; a deployment with no store
configured yields ``unconfigured``. Either way the builders use env (A5), which is operator
controlled, so a store outage cannot widen access.

Revisions: a single key's revision is its document ``version``; ``write_targets``'s is the sum of
its active documents' versions (every create or replace raises it). ``restart_required`` compares
the stored revision now with the revision in the snapshot the process started with.

:class:`StoredSettingsCache` keeps one snapshot per process and deployment key, so the API's
composition root and the scan bootstrap read the same values (no hot reload). Loaded and
unavailable results are cached; ``unconfigured`` is cheap and is not.
"""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Callable, Coroutine, Hashable, Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Final, Literal

from neurosphere_contracts.admin.v1.admin_config_document import AdminConfigDocument
from neurosphere_contracts.admin.v1.system_setting import SystemSetting

from neurosphere_core.admin.models import CloudName
from neurosphere_core.admin.runtime.keys import (
    SYSTEM_SETTING_KIND,
    WRITE_TARGETS,
    SettingKey,
    key_of_document,
)
from neurosphere_core.admin.runtime.validators import validate_setting
from neurosphere_core.admin.store import MAX_LIST_LIMIT, AdminConfigRepository
from neurosphere_core.errors import InvalidSchemaError

__all__ = [
    "DEFAULT_LOAD_TIMEOUT_SECONDS",
    "PROCESS_CACHE",
    "STORED_SETTINGS_UNAVAILABLE",
    "STORED_SETTINGS_UNCONFIGURED",
    "SnapshotStatus",
    "StoredSetting",
    "StoredSettingsCache",
    "StoredSettingsSnapshot",
    "load_stored_settings",
    "revision_of",
    "run_blocking",
    "snapshot_from_documents",
]

DEFAULT_LOAD_TIMEOUT_SECONDS: Final = 10.0
STORED_SETTINGS_UNAVAILABLE: Final = "stored_settings_unavailable"
STORED_SETTINGS_UNCONFIGURED: Final = "stored_settings_unconfigured"

SnapshotStatus = Literal["loaded", "unavailable", "unconfigured"]


def _empty_map() -> Mapping[str, Any]:
    return MappingProxyType({})


@dataclass(frozen=True, slots=True)
class StoredSetting:
    """One validated stored document."""

    key: SettingKey
    document_id: str
    setting: SystemSetting
    version: int
    etag: str


@dataclass(frozen=True, slots=True)
class StoredSettingsSnapshot:
    status: SnapshotStatus
    reason: str | None = None
    #: Single-document keys (every key but ``write_targets``).
    entries: Mapping[str, StoredSetting] = field(default_factory=_empty_map)
    write_targets: tuple[StoredSetting, ...] = ()
    #: Keys whose stored document no longer validates (env applies to them).
    invalid: frozenset[str] = frozenset()

    @classmethod
    def empty(cls, status: SnapshotStatus, reason: str | None = None) -> StoredSettingsSnapshot:
        return cls(status=status, reason=reason)

    def get(self, key: SettingKey) -> StoredSetting | None:
        return self.entries.get(key)

    def setting(self, key: SettingKey) -> SystemSetting | None:
        entry = self.entries.get(key)
        return None if entry is None else entry.setting

    def has(self, key: SettingKey) -> bool:
        return bool(self.write_targets) if key == WRITE_TARGETS else key in self.entries

    def revision(self, key: SettingKey) -> int | None:
        if key == WRITE_TARGETS:
            return sum(e.version for e in self.write_targets) if self.write_targets else None
        entry = self.entries.get(key)
        return None if entry is None else entry.version


def revision_of(key: SettingKey, documents: list[AdminConfigDocument]) -> int | None:
    """The stored revision of ``key`` from its active documents (see module doc)."""
    versions = [
        d.version.root
        for d in documents
        if d.status == "active" and key_of_document(d.id.root) == key
    ]
    if not versions:
        return None
    return sum(versions) if key == WRITE_TARGETS else versions[0]


def _entry(document: AdminConfigDocument, customer_id: str, cloud: CloudName) -> StoredSetting:
    key = key_of_document(document.id.root)
    if key is None:
        raise InvalidSchemaError("unknown stored setting", reason="unknown_setting_key")
    # Dump WITH nulls: ``resource_id``/``credential`` are required-but-nullable members, and
    # ``validate_admin_body`` drops nulls from a model it is handed.
    raw = document.body.model_dump(mode="json")
    setting = validate_setting(key, raw, customer_id=customer_id, cloud=cloud)
    return StoredSetting(key, document.id.root, setting, document.version.root, document.etag.root)


def snapshot_from_documents(
    documents: list[AdminConfigDocument], *, customer_id: str, cloud: CloudName
) -> StoredSettingsSnapshot:
    entries: dict[str, StoredSetting] = {}
    targets: list[StoredSetting] = []
    invalid: set[str] = set()
    for document in documents:
        if document.status != "active":
            continue
        try:
            entry = _entry(document, customer_id, cloud)
        except InvalidSchemaError:
            key = key_of_document(document.id.root)
            if key is not None:
                invalid.add(key)
            continue
        if entry.key == WRITE_TARGETS:
            targets.append(entry)
        else:
            entries[entry.key] = entry
    return StoredSettingsSnapshot(
        status="loaded",
        entries=MappingProxyType(entries),
        write_targets=tuple(sorted(targets, key=lambda e: e.document_id)),
        invalid=frozenset(invalid),
    )


async def load_stored_settings(
    repository: AdminConfigRepository,
    customer_id: str,
    *,
    cloud: CloudName,
    limit_seconds: float = DEFAULT_LOAD_TIMEOUT_SECONDS,
) -> StoredSettingsSnapshot:
    """One bounded read of every stored runtime setting; never raises (see module doc)."""
    try:
        async with asyncio.timeout(limit_seconds):
            documents = await repository.list_by_kind(
                customer_id, SYSTEM_SETTING_KIND, limit=MAX_LIST_LIMIT
            )
    except Exception:
        return StoredSettingsSnapshot.empty("unavailable", STORED_SETTINGS_UNAVAILABLE)
    return snapshot_from_documents(documents, customer_id=customer_id, cloud=cloud)


def run_blocking(
    load: Callable[[], Coroutine[Any, Any, StoredSettingsSnapshot]],
    *,
    limit_seconds: float = DEFAULT_LOAD_TIMEOUT_SECONDS,
) -> StoredSettingsSnapshot:
    """Run ``load`` on its own event loop in a helper thread (callable from sync startup code,
    with or without a running loop); a hang or error past ``limit_seconds`` is ``unavailable``."""
    box: list[StoredSettingsSnapshot] = []

    def target() -> None:
        try:
            box.append(asyncio.run(load()))
        except Exception:
            box.append(StoredSettingsSnapshot.empty("unavailable", STORED_SETTINGS_UNAVAILABLE))

    worker = threading.Thread(target=target, name="ns-stored-settings", daemon=True)
    worker.start()
    worker.join(limit_seconds + 1.0)
    if worker.is_alive() or not box:
        return StoredSettingsSnapshot.empty("unavailable", STORED_SETTINGS_UNAVAILABLE)
    return box[0]


class StoredSettingsCache:
    """One snapshot per process and deployment key (no hot reload, A1)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._entries: dict[Hashable, StoredSettingsSnapshot] = {}

    def get_or_load(
        self, key: Hashable, loader: Callable[[], StoredSettingsSnapshot]
    ) -> StoredSettingsSnapshot:
        with self._lock:
            cached = self._entries.get(key)
            if cached is not None:
                return cached
            snapshot = loader()
            if snapshot.status != "unconfigured":
                self._entries[key] = snapshot
            return snapshot

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()


#: The process-wide cache (tests call ``PROCESS_CACHE.clear()``).
PROCESS_CACHE: Final = StoredSettingsCache()
