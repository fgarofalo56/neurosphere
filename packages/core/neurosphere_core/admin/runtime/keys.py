"""Stored runtime setting keys and their ``admin_config`` document ids (PRP-45).

Six keys, one per runtime feature the operator manages instead of environment variables. Five
keys hold one document each (``system.<key>``); ``write_targets`` holds at most one document per
target kind (``system.write_target.<target_kind>``, PRP-54 lifts the one-per-kind limit). Every
document is kind ``system_setting`` and its body is a ``SystemSetting`` whose ``setting_key``
names the member: the key itself, except ``write_targets`` whose member is ``write_target``.
"""

from __future__ import annotations

from typing import Final, Literal, get_args

__all__ = [
    "DOCUMENT_PREFIX",
    "SETTING_KEYS",
    "SYSTEM_SETTING_KIND",
    "WRITE_TARGETS",
    "SettingKey",
    "document_id",
    "is_setting_key",
    "key_of_document",
    "member_of",
]

SettingKey = Literal["copilot", "judge", "search", "scan", "mcp_server", "write_targets"]
#: Every stored runtime setting key, in display order.
SETTING_KEYS: Final[tuple[SettingKey, ...]] = get_args(SettingKey)
#: The list-valued key (one document per write-target kind).
WRITE_TARGETS: Final = "write_targets"
#: ``admin_config`` kind of every stored runtime setting.
SYSTEM_SETTING_KIND: Final = "system_setting"
DOCUMENT_PREFIX: Final = "system."
_WRITE_TARGET_PREFIX: Final = f"{DOCUMENT_PREFIX}write_target."
_TARGET_KINDS: Final = frozenset({"apim", "foundry"})


def is_setting_key(value: str) -> bool:
    return value in SETTING_KEYS


def member_of(key: SettingKey) -> str:
    """The ``SystemSetting`` member (and ``setting_key`` value) a key's documents carry."""
    return "write_target" if key == WRITE_TARGETS else key


def document_id(key: SettingKey, target_kind: str | None = None) -> str:
    """``system.<key>``; ``system.write_target.<target_kind>`` for ``write_targets``."""
    if key == WRITE_TARGETS:
        if target_kind not in _TARGET_KINDS:
            raise ValueError("write_targets documents need a target kind")
        return f"{_WRITE_TARGET_PREFIX}{target_kind}"
    if target_kind is not None:
        raise ValueError("only write_targets documents carry a target kind")
    return f"{DOCUMENT_PREFIX}{key}"


def key_of_document(doc_id: str) -> SettingKey | None:
    """The setting key a document id belongs to, ``None`` for an id this module never writes."""
    if doc_id.startswith(_WRITE_TARGET_PREFIX):
        return WRITE_TARGETS if doc_id[len(_WRITE_TARGET_PREFIX) :] in _TARGET_KINDS else None
    if not doc_id.startswith(DOCUMENT_PREFIX):
        return None
    key = doc_id[len(DOCUMENT_PREFIX) :]
    if key == WRITE_TARGETS or not is_setting_key(key):
        return None
    return key  # type: ignore[return-value]
