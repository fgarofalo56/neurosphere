# GENERATED - do not edit.
# Source of truth: packages/contracts/schemas/ (JSON Schema 2020-12).
# Regenerate: python packages/contracts/scripts/generate.py
# Drift check: python packages/contracts/scripts/generate.py --check (ADR-0004).
# pyright: reportAssignmentType=false, reportInvalidTypeForm=false

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    RootModel,
    StrictBool,
    StrictInt,
    StrictStr,
)


class Cursor(RootModel[StrictStr]):
    root: Annotated[StrictStr, Field(pattern="^[A-Za-z0-9_-]{1,512}$")]
    """
    Opaque, server-signed, base64url cursor. It encodes position only, never query text or filters, and is bound server-side to the caller's IdentityScope.
    """


class Page(BaseModel):
    """
    Shared cursor-based pagination block returned with every list response (PRP-01 clarification 15). The root schema is the response-side page; $defs/cursor is the opaque cursor a client echoes back on the next request. Cursors are server-issued and server-signed; a cursor that fails signature or scope binding is rejected as invalid_schema (behaviour in PRP-05, not expressible here). Not a standalone document, so it carries no schema_version. has_more=false with next_cursor non-null is rejected by the schema; returned <= limit is checked by tests/contracts/validators.py::check_page_counts.
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    limit: Annotated[StrictInt, Field(ge=1, le=1000)]
    """
    Effective limit applied by the server after clamping the requested Budget.limit.
    """
    returned: Annotated[StrictInt, Field(ge=0)]
    """
    Items returned in this page.
    """
    has_more: StrictBool
    next_cursor: Cursor | None
    """
    Cursor for the next page, or null when has_more is false.
    """
    truncated: StrictBool
    """
    True when a budget other than limit stopped the result early (partial result, must be labelled in the UI).
    """
    truncation_reason: Literal["max_nodes", "max_edges", "max_depth", "timeout_ms"] | None = None
    """
    Which budget stopped the result. Required when truncated is true.
    """
