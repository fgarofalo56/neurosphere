"""Size and depth limits for untrusted input from external MCP servers.

Chosen limits (PRP-22 item 2). They are deliberately tight: a tool manifest is read by an
administrator before approval and later presented to a model, so a large manifest is both a
review burden and a prompt-injection surface.

==========================  =========  =======================================================
Limit                       Default    Why
==========================  =========  =======================================================
max_tools                   128        One server rarely needs more; bounds admin review work
max_name_chars              128        MCP spec tool-name bound (``[A-Za-z0-9_.-]{1,128}``)
max_title_bytes             256        A title is a label, not documentation
max_description_bytes       4096       UTF-8 bytes; enough for real docs, small for injection
max_schema_bytes            16384      Canonical JSON bytes of one input/output schema
max_annotations_bytes       2048       Canonical JSON bytes of the annotations object
max_schema_depth            16         Nesting depth of any schema/annotations value
max_schema_nodes            2000       Total JSON nodes in one schema (width bound)
max_manifest_bytes          262144     256 KiB canonical JSON over every hashed tool
max_list_pages              8          ``tools/list`` pagination cap (a pager cannot loop)
max_result_bytes            65536      Canonical JSON bytes of text + structured content
max_result_blocks           32         Content blocks examined in one tool result
max_response_bytes          1048576    1 MiB per HTTP response body, enforced in transport
==========================  =========  =======================================================
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

__all__ = ["ManifestLimits", "ResultLimits", "TransportLimits"]


class ManifestLimits(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    max_tools: int = Field(default=128, ge=1, le=1024)
    max_name_chars: int = Field(default=128, ge=1, le=128)
    max_title_bytes: int = Field(default=256, ge=1, le=4096)
    max_description_bytes: int = Field(default=4096, ge=1, le=65536)
    max_schema_bytes: int = Field(default=16384, ge=64, le=262144)
    max_annotations_bytes: int = Field(default=2048, ge=2, le=65536)
    max_schema_depth: int = Field(default=16, ge=2, le=64)
    max_schema_nodes: int = Field(default=2000, ge=1, le=100000)
    max_manifest_bytes: int = Field(default=262144, ge=1024, le=4194304)
    max_list_pages: int = Field(default=8, ge=1, le=64)


class ResultLimits(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    max_result_bytes: int = Field(default=65536, ge=256, le=1048576)
    max_result_blocks: int = Field(default=32, ge=1, le=256)
    max_depth: int = Field(default=16, ge=2, le=64)


class TransportLimits(BaseModel):
    """Per-request network bounds applied by the API transport (seconds and bytes)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    connect_timeout_seconds: float = Field(default=5.0, gt=0, le=60)
    read_timeout_seconds: float = Field(default=15.0, gt=0, le=120)
    write_timeout_seconds: float = Field(default=10.0, gt=0, le=60)
    operation_timeout_seconds: float = Field(default=30.0, gt=0, le=300)
    dns_timeout_seconds: float = Field(default=5.0, gt=0, le=30)
    max_response_bytes: int = Field(default=1048576, ge=4096, le=16777216)
    max_connections: int = Field(default=4, ge=1, le=32)
