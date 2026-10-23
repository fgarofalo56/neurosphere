"""Registry models for external MCP servers: registration, tool manifest entries and approvals.

One document per registered server (:class:`RegisteredServer`) holds the server's tool records.
Each :class:`ToolRecord` pairs the latest manifest entry the server advertised with its approval
state and, once approved, a snapshot of the approved entry so an administrator can diff a changed
tool before re-approving it.

Integrity on load: :class:`ToolManifestEntry` recomputes its ``tool_hash`` and
:class:`RegisteredServer` re-normalises its URL and recomputes its id, so a stored document that
was edited out of band fails validation instead of silently changing what is callable.
"""

from __future__ import annotations

import re
from typing import Any, Final, Literal, Self

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from neurosphere_core.audit.canonical import digests_equal, sha256_digest
from neurosphere_core.cloud import CloudName
from neurosphere_core.mcp.urls import (
    host_matches_suffix,
    normalize_host_suffix,
    normalize_server_url,
    server_id_for,
)

__all__ = [
    "DEFAULT_GOVERNMENT_HOST_SUFFIXES",
    "HASH_PATTERN",
    "ApprovalState",
    "McpClientPolicy",
    "RegisteredServer",
    "ServerStatus",
    "SyncResult",
    "ToolApproval",
    "ToolManifestEntry",
    "ToolRecord",
    "compute_tool_hash",
    "tool_hash_input",
]

HASH_PATTERN: Final = r"^sha256:[0-9a-f]{64}$"
_TOOL_NAME_RE: Final = re.compile(r"^[A-Za-z0-9_.-]{1,128}$")

#: Government boundary default: Azure Government service suffixes. Deployments narrow or extend
#: this through :class:`McpClientPolicy`; matching is whole-label on the parsed hostname.
DEFAULT_GOVERNMENT_HOST_SUFFIXES: Final = (".usgovcloudapi.net", ".azure.us")

ApprovalState = Literal["pending", "approved", "revoked", "removed"]
ServerStatus = Literal["active", "disabled"]


def tool_hash_input(
    *,
    name: str,
    title: str | None,
    description: str,
    input_schema: dict[str, Any],
    output_schema: dict[str, Any] | None,
    annotations: dict[str, Any] | None,
) -> dict[str, Any]:
    """The hashed object: every field a person or a model reads. Absent members hash as null."""
    return {
        "name": name,
        "title": title,
        "description": description,
        "input_schema": input_schema,
        "output_schema": output_schema,
        "annotations": annotations,
    }


def compute_tool_hash(**fields: Any) -> str:
    """``sha256:<hex>`` over the RFC 8785 form of :func:`tool_hash_input`."""
    return sha256_digest(tool_hash_input(**fields))


class ToolManifestEntry(BaseModel):
    """One validated tool from an external manifest (see :mod:`neurosphere_core.mcp.manifest`)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str = Field(min_length=1, max_length=128)
    title: str | None = None
    description: str
    input_schema: dict[str, Any]
    output_schema: dict[str, Any] | None = None
    annotations: dict[str, Any] | None = None
    tool_hash: str = Field(pattern=HASH_PATTERN)

    @model_validator(mode="after")
    def _hash_matches(self) -> Self:
        if not _TOOL_NAME_RE.fullmatch(self.name):
            raise ValueError("tool name must match [A-Za-z0-9_.-]{1,128}")
        expected = compute_tool_hash(
            name=self.name,
            title=self.title,
            description=self.description,
            input_schema=self.input_schema,
            output_schema=self.output_schema,
            annotations=self.annotations,
        )
        if not digests_equal(expected, self.tool_hash):
            raise ValueError("tool_hash does not match the entry content")
        return self


class ToolApproval(BaseModel):
    """Approval state of one tool. ``approved_hash`` survives revocation for the admin diff."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    state: ApprovalState
    approved_hash: str | None = Field(default=None, pattern=HASH_PATTERN)
    approved_by: str | None = None
    approved_at: AwareDatetime | None = None
    revoked_reason: str | None = Field(default=None, max_length=200)
    revoked_by: str | None = None
    updated_at: AwareDatetime

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        if self.state == "approved" and (
            self.approved_hash is None or self.approved_by is None or self.approved_at is None
        ):
            raise ValueError("an approved tool needs approved_hash, approved_by and approved_at")
        if self.state == "revoked" and self.revoked_reason is None:
            raise ValueError("a revoked tool needs revoked_reason")
        return self


class ToolRecord(BaseModel):
    """Latest advertised entry, approval state and the approved snapshot (if ever approved)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str
    entry: ToolManifestEntry
    approval: ToolApproval
    approved_entry: ToolManifestEntry | None = None
    first_seen_at: AwareDatetime
    last_seen_at: AwareDatetime

    @model_validator(mode="after")
    def _names_agree(self) -> Self:
        if self.entry.name != self.name or (
            self.approved_entry is not None and self.approved_entry.name != self.name
        ):
            raise ValueError("tool record name must match its entries")
        if (
            self.approval.approved_hash is not None
            and self.approved_entry is not None
            and not digests_equal(self.approval.approved_hash, self.approved_entry.tool_hash)
        ):
            raise ValueError("approved_entry must be the entry whose hash was approved")
        return self

    @property
    def callable_hash(self) -> str | None:
        """The hash that may be called: approved AND the latest advertised entry is that hash."""
        approval = self.approval
        if approval.state != "approved" or approval.approved_hash is None:
            return None
        if not digests_equal(approval.approved_hash, self.entry.tool_hash):
            return None
        return approval.approved_hash


class RegisteredServer(BaseModel):
    """An administrator-registered external MCP server (exact HTTPS URL, no discovery)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(pattern=r"^mcp-[0-9a-f]{32}$")
    url: str
    host: str
    port: int = Field(ge=1, le=65535)
    display_name: str = Field(min_length=1, max_length=200)
    cloud: CloudName
    registered_by: str = Field(min_length=1, max_length=512)
    registered_at: AwareDatetime
    status: ServerStatus = "active"
    etag: str | None = None
    last_synced_at: AwareDatetime | None = None
    manifest_hash: str | None = Field(default=None, pattern=HASH_PATTERN)
    tools: tuple[ToolRecord, ...] = ()

    @model_validator(mode="after")
    def _url_is_normalised(self) -> Self:
        normalised = normalize_server_url(self.url)
        if normalised.url != self.url or normalised.host != self.host:
            raise ValueError("url must be the normalised exact server URL")
        if normalised.port != self.port or server_id_for(normalised) != self.id:
            raise ValueError("id and port must be derived from the url")
        names = [t.name for t in self.tools]
        if len(names) != len(set(names)):
            raise ValueError("tool names must be unique per server")
        return self

    def tool(self, name: str) -> ToolRecord | None:
        return next((t for t in self.tools if t.name == name), None)

    def to_document(self) -> dict[str, Any]:
        return self.model_dump(mode="json", exclude={"etag"})

    @classmethod
    def from_document(cls, document: dict[str, Any], *, etag: str | None) -> RegisteredServer:
        return cls.model_validate({**document, "etag": etag})


class SyncResult(BaseModel):
    """Outcome of applying one validated manifest to a registered server."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    server_id: str
    synced_at: AwareDatetime
    manifest_hash: str = Field(pattern=HASH_PATTERN)
    added: tuple[str, ...] = ()
    changed: tuple[str, ...] = ()
    revoked: tuple[str, ...] = ()
    removed: tuple[str, ...] = ()
    unchanged: tuple[str, ...] = ()


class McpClientPolicy(BaseModel):
    """Deployment policy for external MCP servers (the setting item 3 wires from config).

    ``cloud`` is the deployment's cloud. In Government every registration and every connection
    must target a host inside ``government_host_suffixes`` (whole-label suffix match on the
    parsed hostname; IP literals are never inside the boundary).
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    cloud: CloudName
    government_host_suffixes: tuple[str, ...] = DEFAULT_GOVERNMENT_HOST_SUFFIXES

    @model_validator(mode="after")
    def _suffixes_normalised(self) -> Self:
        for suffix in self.government_host_suffixes:
            if normalize_host_suffix(suffix) != suffix:
                raise ValueError("government_host_suffixes must be lowercase '.a.b' suffixes")
        return self

    def host_in_boundary(self, host: str, *, ip_literal: bool) -> bool:
        if self.cloud is CloudName.COMMERCIAL:
            return True
        if ip_literal:
            return False
        return host_matches_suffix(host, self.government_host_suffixes)
