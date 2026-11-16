"""Stored runtime settings (PRP-45): keys, per-key validators and the startup snapshot.

The operator stores copilot, judge, search, scan, MCP server and write-target settings in the
``admin_config`` store (kind ``system_setting``) instead of environment variables. The API
builders and the worker evaluation role read one :class:`StoredSettingsSnapshot` at startup and
pass stored fields as init arguments to their existing settings classes (stored over env, A2;
restart to apply, A1). Write-target entries are validated and listed only; PRP-54 registers them.
"""

from neurosphere_core.admin.runtime.keys import (
    SETTING_KEYS,
    SYSTEM_SETTING_KIND,
    WRITE_TARGETS,
    SettingKey,
    document_id,
    is_setting_key,
    key_of_document,
    member_of,
)
from neurosphere_core.admin.runtime.snapshot import (
    DEFAULT_LOAD_TIMEOUT_SECONDS,
    PROCESS_CACHE,
    STORED_SETTINGS_UNAVAILABLE,
    STORED_SETTINGS_UNCONFIGURED,
    SnapshotStatus,
    StoredSetting,
    StoredSettingsCache,
    StoredSettingsSnapshot,
    load_stored_settings,
    revision_of,
    run_blocking,
    snapshot_from_documents,
)
from neurosphere_core.admin.runtime.validators import (
    CREDENTIAL_MARKERS,
    copilot_init_args,
    judge_init_args,
    mcp_server_init_args,
    refuse_credential_names,
    scan_init_args,
    search_init_args,
    search_service_name,
    validate_setting,
)

__all__ = [
    "CREDENTIAL_MARKERS",
    "DEFAULT_LOAD_TIMEOUT_SECONDS",
    "PROCESS_CACHE",
    "SETTING_KEYS",
    "STORED_SETTINGS_UNAVAILABLE",
    "STORED_SETTINGS_UNCONFIGURED",
    "SYSTEM_SETTING_KIND",
    "WRITE_TARGETS",
    "SettingKey",
    "SnapshotStatus",
    "StoredSetting",
    "StoredSettingsCache",
    "StoredSettingsSnapshot",
    "copilot_init_args",
    "document_id",
    "is_setting_key",
    "judge_init_args",
    "key_of_document",
    "load_stored_settings",
    "mcp_server_init_args",
    "member_of",
    "refuse_credential_names",
    "revision_of",
    "run_blocking",
    "scan_init_args",
    "search_init_args",
    "search_service_name",
    "snapshot_from_documents",
    "validate_setting",
]
