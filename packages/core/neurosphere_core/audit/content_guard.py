"""Metadata-only guard for audit records (PRP-06 C11, C15).

Audit records carry actor pseudonyms, operation names, target ids and versions, scope hashes,
decisions, reason codes, correlation ids and digests. They never carry prompt or response
bodies, tokens, credentials, e-mail addresses / UPNs or raw directory object ids.

:func:`assert_metadata_only` runs inside ``seal`` (the only way a record is created), so no
builder, caller or future code path can bypass it. Findings are reported as JSON pointers plus
a category; the offending value is never echoed (it may be the secret).
"""

from __future__ import annotations

import re
from collections.abc import Iterator, Mapping
from typing import Any, Final

from neurosphere_core.errors import InvalidSchemaError, ValidationIssue

# Keys that would only exist if someone tried to smuggle a body or credential into a record.
FORBIDDEN_KEYS: Final = frozenset(
    {
        "prompt",
        "prompts",
        "response",
        "responses",
        "completion",
        "messages",
        "body",
        "request_body",
        "response_body",
        "token",
        "access_token",
        "id_token",
        "refresh_token",
        "authorization",
        "password",
        "secret",
        "client_secret",
        "upn",
        "email",
        "oid",
        "object_id",
    }
)

_JWT: Final = re.compile(r"eyJ[A-Za-z0-9_-]{4,}\.[A-Za-z0-9_-]{4,}\.?")
_BEARER: Final = re.compile(r"(?i)\bbearer\s+\S")
_EMAIL: Final = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_CONN_SECRET: Final = re.compile(r"(?i)\b(accountkey|sharedaccesskey|password|pwd|sig)=")
_PEM: Final = re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")
GUID: Final = re.compile(r"(?i)[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")

# outcome.detail is a short machine code (``decision=allow``, ``target_drifted``), never prose:
# free text is how a prompt or response body would leak in.
DETAIL_PATTERN: Final = re.compile(r"^[a-z][a-z0-9_.:=-]{0,127}$")

# Server-assigned UUIDs (audit_id, intent_id) and opaque version/snapshot pointers may be
# GUID-shaped (Cosmos ETags are). Directory object ids are only plausible in the fields
# below that are NOT listed here, and in person canonical ids (checked separately).
_GUID_ALLOWED: Final = frozenset(
    {"/audit_id", "/intent_id", "/subject/target_version", "/subject/snapshot_ref"}
)
_CANONICAL_ID_POINTER: Final = "/subject/target/canonical_id"
_PERSON_TYPES: Final = frozenset({"person", "user", "principal", "owner"})


def _walk(value: Any, pointer: str = "") -> Iterator[tuple[str, str | None, Any]]:
    """Yield (pointer, key, value) for every node below ``value``."""
    if isinstance(value, Mapping):
        for key, item in value.items():  # pyright: ignore[reportUnknownVariableType]
            child = f"{pointer}/{key}"
            yield child, str(key), item  # pyright: ignore[reportUnknownArgumentType]
            yield from _walk(item, child)
    elif isinstance(value, list | tuple):
        for index, item in enumerate(value):  # pyright: ignore[reportUnknownVariableType, reportUnknownArgumentType]
            child = f"{pointer}/{index}"
            yield child, None, item
            yield from _walk(item, child)


def _is_person_canonical_id(value: str) -> bool:
    parts = value.split(":")
    return len(parts) >= 5 and parts[3] in _PERSON_TYPES


def _string_findings(pointer: str, text: str) -> list[str]:
    found: list[str] = []
    if _JWT.search(text):
        found.append("jwt")
    if _BEARER.search(text):
        found.append("bearer_token")
    if _EMAIL.search(text):
        found.append("email_or_upn")
    if _CONN_SECRET.search(text):
        found.append("credential")
    if _PEM.search(text):
        found.append("private_key")
    if GUID.search(text):
        if pointer == _CANONICAL_ID_POINTER:
            if _is_person_canonical_id(text):
                found.append("raw_object_id")
        elif pointer not in _GUID_ALLOWED:
            found.append("raw_object_id")
    if pointer == "/outcome/detail" and not DETAIL_PATTERN.fullmatch(text):
        found.append("free_text_detail")
    return found


def find_sensitive_content(document: Mapping[str, Any]) -> list[tuple[str, str]]:
    """Return ``(json_pointer, category)`` for every disallowed value in ``document``."""
    findings: list[tuple[str, str]] = []
    for pointer, key, value in _walk(document):
        if key is not None and key.lower() in FORBIDDEN_KEYS:
            findings.append((pointer, "forbidden_field"))
        if isinstance(value, str):
            findings.extend((pointer, category) for category in _string_findings(pointer, value))
    return findings


def assert_metadata_only(document: Mapping[str, Any]) -> None:
    """Raise ``invalid_schema`` (reason ``audit_content_rejected``) on any finding."""
    findings = find_sensitive_content(document)
    if findings:
        raise InvalidSchemaError(
            "audit record rejected: it must carry metadata and decisions only",
            reason="audit_content_rejected",
            errors=[
                ValidationIssue(pointer, f"disallowed content: {cat}") for pointer, cat in findings
            ],
        )
