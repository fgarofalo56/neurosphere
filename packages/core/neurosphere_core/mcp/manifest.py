"""Validation, bounding and hashing of an external server's tool manifest (untrusted input).

:func:`validate_manifest` takes the raw ``tools`` list exactly as the server sent it (JSON
objects with the MCP wire names ``name``, ``title``, ``description``, ``inputSchema``,
``outputSchema``, ``annotations``) and returns a :class:`ValidatedManifest` of
:class:`~neurosphere_core.mcp.models.ToolManifestEntry` values, each hashed over canonical JSON of
everything a person or model reads. Members outside that set (``icons``, ``_meta``, ...) are
neither hashed nor kept: nothing downstream can surface them.

Malformed input raises ``invalid_schema`` reason ``invalid_manifest``; input over a limit in
:class:`~neurosphere_core.mcp.limits.ManifestLimits` raises ``invalid_schema`` reason
``manifest_too_large``. Pointers name the offending member; messages never echo values.
"""

from __future__ import annotations

import json
import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final

from neurosphere_core.audit.canonical import canonical_json, sha256_digest
from neurosphere_core.errors import InvalidSchemaError, ValidationIssue
from neurosphere_core.mcp.errors import INVALID_MANIFEST, MANIFEST_TOO_LARGE, invalid
from neurosphere_core.mcp.limits import ManifestLimits
from neurosphere_core.mcp.models import ToolManifestEntry, compute_tool_hash

__all__ = [
    "ValidatedManifest",
    "json_size",
    "measure_json",
    "validate_manifest",
]

_TOOL_NAME_RE: Final = re.compile(r"^[A-Za-z0-9_.-]+$")


@dataclass(frozen=True, slots=True)
class ValidatedManifest:
    tools: tuple[ToolManifestEntry, ...]
    manifest_hash: str
    total_bytes: int

    def by_name(self) -> dict[str, ToolManifestEntry]:
        return {t.name: t for t in self.tools}


class _ManifestError(Exception):
    def __init__(self, reason: str, pointer: str, detail: str) -> None:
        super().__init__(detail)
        self.reason = reason
        self.pointer = pointer
        self.detail = detail


def measure_json(value: Any, *, max_depth: int, max_nodes: int) -> None:
    """Raise ``ValueError`` unless ``value`` is plain JSON within depth and node bounds."""
    stack: list[tuple[Any, int]] = [(value, 1)]
    nodes = 0
    while stack:
        item, depth = stack.pop()
        nodes += 1
        if nodes > max_nodes:
            raise OverflowError("too many JSON nodes")
        if depth > max_depth:
            raise OverflowError("JSON nesting too deep")
        if item is None or isinstance(item, bool | str | int):
            continue
        if isinstance(item, float):
            if not math.isfinite(item):
                raise ValueError("non-finite number")
            continue
        if isinstance(item, Mapping):
            for key, child in item.items():  # pyright: ignore[reportUnknownVariableType]
                if not isinstance(key, str):
                    raise ValueError("object keys must be strings")
                stack.append((child, depth + 1))
            continue
        if isinstance(item, list | tuple):
            stack.extend((child, depth + 1) for child in item)  # pyright: ignore[reportUnknownVariableType]
            continue
        raise ValueError("not a JSON value")


def json_size(value: Any) -> int:
    """UTF-8 byte length of the canonical JSON form."""
    return len(canonical_json(value).encode("utf-8"))


def _text(value: Any, pointer: str, *, max_bytes: int, required: bool) -> str | None:
    if value is None:
        if required:
            raise _ManifestError(INVALID_MANIFEST, pointer, "is required")
        return None
    if not isinstance(value, str):
        raise _ManifestError(INVALID_MANIFEST, pointer, "must be a string")
    if len(value.encode("utf-8", errors="surrogatepass")) > max_bytes:
        raise _ManifestError(MANIFEST_TOO_LARGE, pointer, f"exceeds {max_bytes} bytes")
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        raise _ManifestError(INVALID_MANIFEST, pointer, "is not valid Unicode text") from None
    return value


def _object(
    value: Any,
    pointer: str,
    limits: ManifestLimits,
    *,
    max_bytes: int,
    schema: bool,
) -> dict[str, Any] | None:
    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise _ManifestError(INVALID_MANIFEST, pointer, "must be a JSON object")
    try:
        measure_json(value, max_depth=limits.max_schema_depth, max_nodes=limits.max_schema_nodes)
    except OverflowError as exc:
        raise _ManifestError(MANIFEST_TOO_LARGE, pointer, str(exc)) from None
    except ValueError as exc:
        raise _ManifestError(INVALID_MANIFEST, pointer, str(exc)) from None
    try:
        text = canonical_json(value)
        size = len(text.encode("utf-8"))
    except UnicodeEncodeError:
        raise _ManifestError(INVALID_MANIFEST, pointer, "is not valid Unicode text") from None
    if size > max_bytes:
        raise _ManifestError(MANIFEST_TOO_LARGE, pointer, f"exceeds {max_bytes} bytes")
    copied: dict[str, Any] = json.loads(text)  # detached deep copy of the untrusted value
    if schema and copied.get("type") != "object":
        raise _ManifestError(
            INVALID_MANIFEST, pointer, 'must be a JSON Schema with "type": "object"'
        )
    return copied


def _entry(raw: Any, index: int, limits: ManifestLimits) -> ToolManifestEntry:
    base = f"/tools/{index}"
    if not isinstance(raw, Mapping):
        raise _ManifestError(INVALID_MANIFEST, base, "must be a JSON object")
    tool: Mapping[str, Any] = raw  # pyright: ignore[reportUnknownVariableType]
    if not all(isinstance(k, str) for k in tool):
        raise _ManifestError(INVALID_MANIFEST, base, "object keys must be strings")
    name = tool.get("name")
    if (
        not isinstance(name, str)
        or not 1 <= len(name) <= limits.max_name_chars
        or not _TOOL_NAME_RE.fullmatch(name)
    ):
        raise _ManifestError(INVALID_MANIFEST, f"{base}/name", "must match [A-Za-z0-9_.-]{1,128}")
    title = _text(
        tool.get("title"), f"{base}/title", max_bytes=limits.max_title_bytes, required=False
    )
    description = _text(
        tool.get("description"),
        f"{base}/description",
        max_bytes=limits.max_description_bytes,
        required=False,
    )
    if "inputSchema" not in tool:
        raise _ManifestError(INVALID_MANIFEST, f"{base}/inputSchema", "is required")
    input_schema = _object(
        tool.get("inputSchema"),
        f"{base}/inputSchema",
        limits,
        max_bytes=limits.max_schema_bytes,
        schema=True,
    )
    if input_schema is None:
        raise _ManifestError(INVALID_MANIFEST, f"{base}/inputSchema", "is required")
    output_schema = _object(
        tool.get("outputSchema"),
        f"{base}/outputSchema",
        limits,
        max_bytes=limits.max_schema_bytes,
        schema=True,
    )
    annotations = _object(
        tool.get("annotations"),
        f"{base}/annotations",
        limits,
        max_bytes=limits.max_annotations_bytes,
        schema=False,
    )
    fields: dict[str, Any] = {
        "name": name,
        "title": title,
        "description": description or "",
        "input_schema": input_schema,
        "output_schema": output_schema,
        "annotations": annotations,
    }
    return ToolManifestEntry(**fields, tool_hash=compute_tool_hash(**fields))


def _raise(bad: _ManifestError) -> InvalidSchemaError:
    detail = (
        "tool manifest exceeds a size limit"
        if bad.reason == MANIFEST_TOO_LARGE
        else ("tool manifest is not valid")
    )
    return invalid(bad.reason, detail, issues=[ValidationIssue(bad.pointer, bad.detail)])


def validate_manifest(
    raw_tools: Sequence[Any], limits: ManifestLimits | None = None
) -> ValidatedManifest:
    """Validate, bound and hash ``raw_tools`` (the concatenated ``tools/list`` pages)."""
    limits = limits or ManifestLimits()
    if isinstance(raw_tools, str | bytes) or not isinstance(raw_tools, Sequence):
        raise _raise(_ManifestError(INVALID_MANIFEST, "/tools", "must be a JSON array"))
    if len(raw_tools) > limits.max_tools:
        raise _raise(
            _ManifestError(MANIFEST_TOO_LARGE, "/tools", f"more than {limits.max_tools} tools")
        )
    entries: list[ToolManifestEntry] = []
    seen: set[str] = set()
    total = 0
    try:
        for index, raw in enumerate(raw_tools):
            entry = _entry(raw, index, limits)
            if entry.name in seen:
                raise _ManifestError(
                    INVALID_MANIFEST, f"/tools/{index}/name", "duplicates another tool"
                )
            seen.add(entry.name)
            total += json_size(entry.model_dump(mode="json"))
            if total > limits.max_manifest_bytes:
                raise _ManifestError(
                    MANIFEST_TOO_LARGE, "/tools", f"exceeds {limits.max_manifest_bytes} bytes"
                )
            entries.append(entry)
    except _ManifestError as bad:
        raise _raise(bad) from None
    entries.sort(key=lambda e: e.name)
    manifest_hash = sha256_digest([{"name": e.name, "tool_hash": e.tool_hash} for e in entries])
    return ValidatedManifest(tools=tuple(entries), manifest_hash=manifest_hash, total_bytes=total)
