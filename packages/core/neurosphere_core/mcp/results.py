"""External tool results: bounded, untrusted DATA with provenance (clarification 11).

An :class:`ExternalToolResult` is what the platform keeps from an external MCP tool call: text
blocks and structured content only (image, audio, resource and resource-link blocks are dropped
and counted in ``omitted_blocks``), bounded by
:class:`~neurosphere_core.mcp.limits.ResultLimits`, stamped with provenance (server, tool, tool
hash, retrieval time) and marked ``trust = "untrusted_external"``.

It is data, never instructions. There is no conversion from a result to an action draft or a
confirmation: this module (and the whole ``neurosphere_core.mcp`` package) does not import
``neurosphere_core.actions``, and a test asserts the import graph stays that way.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any, Final, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from neurosphere_core.audit.canonical import canonical_json
from neurosphere_core.cloud import CloudName
from neurosphere_core.errors import InvalidSchemaError, ValidationIssue
from neurosphere_core.mcp.errors import INVALID_TOOL_RESULT, TOOL_RESULT_TOO_LARGE, invalid
from neurosphere_core.mcp.limits import ResultLimits
from neurosphere_core.mcp.manifest import json_size, measure_json
from neurosphere_core.mcp.models import HASH_PATTERN

__all__ = [
    "UNTRUSTED_EXTERNAL",
    "ExternalTextBlock",
    "ExternalToolProvenance",
    "ExternalToolResult",
    "build_external_result",
]

UNTRUSTED_EXTERNAL: Final = "untrusted_external"


class ExternalToolProvenance(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    server_id: str
    server_url: str
    cloud: CloudName
    tool_name: str
    tool_hash: str = Field(pattern=HASH_PATTERN)
    retrieved_at: AwareDatetime


class ExternalTextBlock(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    type: Literal["text"] = "text"
    text: str


class ExternalToolResult(BaseModel):
    """Untrusted data returned by an approved external tool. Never an instruction or an intent."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    trust: Literal["untrusted_external"] = UNTRUSTED_EXTERNAL
    provenance: ExternalToolProvenance
    is_error: bool
    content: tuple[ExternalTextBlock, ...] = ()
    structured_content: dict[str, Any] | None = None
    omitted_blocks: int = Field(default=0, ge=0)
    size_bytes: int = Field(ge=0)


def _bad(detail: str, pointer: str) -> InvalidSchemaError:
    return invalid(
        INVALID_TOOL_RESULT, "tool result is not valid", issues=[ValidationIssue(pointer, detail)]
    )


def _too_large(pointer: str, detail: str) -> InvalidSchemaError:
    return invalid(
        TOOL_RESULT_TOO_LARGE,
        "tool result exceeds a size limit",
        issues=[ValidationIssue(pointer, detail)],
    )


def _text_blocks(
    raw_content: Sequence[Any], limits: ResultLimits
) -> tuple[list[ExternalTextBlock], int]:
    if isinstance(raw_content, str | bytes) or not isinstance(raw_content, Sequence):
        raise _bad("must be a JSON array", "/content")
    if len(raw_content) > limits.max_result_blocks:
        raise _too_large("/content", f"more than {limits.max_result_blocks} blocks")
    blocks: list[ExternalTextBlock] = []
    omitted = 0
    for index, block in enumerate(raw_content):
        if not isinstance(block, Mapping):
            raise _bad("must be a JSON object", f"/content/{index}")
        kind = block.get("type")  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
        if kind != "text":
            omitted += 1
            continue
        text = block.get("text")  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
        if not isinstance(text, str):
            raise _bad("text block needs a string", f"/content/{index}/text")
        blocks.append(ExternalTextBlock(text=text))
    return blocks, omitted


def build_external_result(
    *,
    provenance: ExternalToolProvenance,
    raw_content: Sequence[Any],
    structured_content: Any,
    is_error: bool,
    limits: ResultLimits | None = None,
) -> ExternalToolResult:
    """Bound and wrap a raw ``CallToolResult``; oversize raises ``invalid_schema``."""
    limits = limits or ResultLimits()
    blocks, omitted = _text_blocks(raw_content, limits)
    structured: dict[str, Any] | None = None
    if structured_content is not None:
        if not isinstance(structured_content, Mapping):
            raise _bad("must be a JSON object", "/structuredContent")
        try:
            measure_json(
                structured_content, max_depth=limits.max_depth, max_nodes=limits.max_result_bytes
            )
        except OverflowError as exc:
            raise _too_large("/structuredContent", str(exc)) from None
        except ValueError as exc:
            raise _bad(str(exc), "/structuredContent") from None
        try:
            structured = json.loads(canonical_json(structured_content))
        except UnicodeEncodeError:
            raise _bad("is not valid Unicode text", "/structuredContent") from None
    try:
        size = json_size({"content": [b.text for b in blocks], "structured_content": structured})
    except UnicodeEncodeError:
        raise _bad("is not valid Unicode text", "/content") from None
    if size > limits.max_result_bytes:
        raise _too_large("/", f"exceeds {limits.max_result_bytes} bytes")
    return ExternalToolResult(
        provenance=provenance,
        is_error=is_error,
        content=tuple(blocks),
        structured_content=structured,
        omitted_blocks=omitted,
        size_bytes=size,
    )
