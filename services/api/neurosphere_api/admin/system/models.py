"""Response models of the system admin API (PRP-45). Names and reason codes only in status and
checklist bodies; stored setting values appear only in the settings routes (deployment admin)."""

from __future__ import annotations

from typing import Any, Literal

from neurosphere_contracts.admin.v1.first_run_checklist_item import FirstRunChecklistItem
from pydantic import BaseModel, ConfigDict

__all__ = [
    "ChecklistPage",
    "ComponentView",
    "DiffEntry",
    "SettingEntry",
    "SettingView",
    "SettingWriteResult",
    "SettingsPage",
    "StoredSettingsState",
    "SystemStatus",
]

_FROZEN = ConfigDict(extra="forbid", frozen=True)


class ComponentView(BaseModel):
    model_config = _FROZEN

    name: str
    state: Literal["ok", "failed", "disabled", "not_built"]
    required: bool
    #: Failure reason code; ``None`` unless ``state`` is ``failed``.
    reason: str | None
    blocks_readiness: bool
    #: A startup step (``cosmos_containers``), not a component.
    step: bool


class StoredSettingsState(BaseModel):
    model_config = _FROZEN

    status: Literal["loaded", "unavailable", "unconfigured"]
    reason: str | None
    #: Keys whose stored document did not validate at startup (env applied instead).
    invalid_keys: list[str]


class SystemStatus(BaseModel):
    model_config = _FROZEN

    ready: bool
    components: list[ComponentView]
    #: Environment probe name -> reason code (``ok``, ``timeout``, ``connection_refused``...).
    probes: dict[str, str]
    stored_settings: StoredSettingsState


class ChecklistPage(BaseModel):
    model_config = _FROZEN

    items: list[FirstRunChecklistItem]


class SettingEntry(BaseModel):
    model_config = _FROZEN

    document_id: str
    version: int
    etag: str
    #: The stored ``SystemSetting`` (endpoints, resource ids and credential references only).
    value: dict[str, Any]


class SettingView(BaseModel):
    model_config = _FROZEN

    key: str
    #: Where the value the runtime applied at startup came from.
    source: Literal["stored", "env", "default"]
    stored_revision: int | None
    applied_revision: int | None
    #: The stored revision differs from the one this process started with (A1: restart).
    restart_required: bool
    #: ``False`` for ``write_targets``: stored entries are listed, PRP-54 registers them.
    applied_by_runtime: bool
    #: ``ETag`` to send as ``If-Match`` for a single-document key (``"absent"`` = nothing stored).
    etag: str | None
    entries: list[SettingEntry]


class SettingsPage(BaseModel):
    model_config = _FROZEN

    items: list[SettingView]
    stored_settings: StoredSettingsState


class DiffEntry(BaseModel):
    model_config = _FROZEN

    pointer: str
    before: Any = None
    after: Any = None


class SettingWriteResult(BaseModel):
    model_config = _FROZEN

    key: str
    document_id: str
    version: int
    etag: str
    stored_revision: int | None
    applied_revision: int | None
    restart_required: bool
    diff: list[DiffEntry]
