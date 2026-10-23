"""Request and response models of the MCP registration-admin API (PRP-22 item 3).

Views are built from the registry records (``neurosphere_core.mcp``); they never carry a
credential, a resolved address or a raw upstream body. A tool that lost its approval because its
advertised content changed carries ``change`` (before/after of the description and schemas) so
the administrator sees exactly what moved before re-approving.

No ``from __future__ import annotations``: FastAPI inspects these models.
"""

from typing import Annotated, Any, Literal, Self

from neurosphere_core.mcp import (
    HASH_CHANGED,
    RegisteredServer,
    SyncResult,
    ToolManifestEntry,
    ToolRecord,
)
from neurosphere_core.mcp.models import HASH_PATTERN
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, StringConstraints, model_validator

__all__ = [
    "ApproveToolBody",
    "RegisterServerBody",
    "ServerPage",
    "ServerView",
    "SyncView",
    "ToolChangeView",
    "ToolEntryView",
    "ToolList",
    "ToolView",
    "UpdateServerBody",
    "server_view",
    "sync_view",
    "tool_list",
    "tool_view",
]

DisplayName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
ToolState = Literal["pending", "approved", "revoked", "removed"]


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RegisterServerBody(_Model):
    url: Annotated[str, Field(min_length=1, max_length=2048)]
    display_name: DisplayName


class UpdateServerBody(_Model):
    display_name: DisplayName | None = None
    status: Literal["active", "disabled"] | None = None

    @model_validator(mode="after")
    def _something_to_change(self) -> Self:
        if self.display_name is None and self.status is None:
            raise ValueError("send display_name, status or both")
        return self


class ApproveToolBody(_Model):
    """The hash the administrator reviewed; approval succeeds only if it is still current."""

    expected_hash: Annotated[str, Field(pattern=HASH_PATTERN)]


class ToolEntryView(_Model):
    name: str
    title: str | None = None
    description: str
    input_schema: dict[str, Any]
    output_schema: dict[str, Any] | None = None
    annotations: dict[str, Any] | None = None
    tool_hash: str


class ToolChangeView(_Model):
    """Approved content (before) against the latest advertised content (after)."""

    before: ToolEntryView
    after: ToolEntryView
    description_changed: bool
    input_schema_changed: bool
    output_schema_changed: bool


class ToolView(_Model):
    name: str
    state: ToolState
    enabled: bool
    current_hash: str
    approved_hash: str | None = None
    approved_by: str | None = None
    approved_at: AwareDatetime | None = None
    revoked_reason: str | None = None
    revoked_by: str | None = None
    first_seen_at: AwareDatetime
    last_seen_at: AwareDatetime
    updated_at: AwareDatetime
    entry: ToolEntryView
    change: ToolChangeView | None = None


class ServerView(_Model):
    id: str
    url: str
    host: str
    display_name: str
    cloud: str
    status: Literal["active", "disabled"]
    registered_by: str
    registered_at: AwareDatetime
    last_synced_at: AwareDatetime | None = None
    manifest_hash: str | None = None
    etag: str | None = None
    tool_count: int
    pending_count: int
    approved_count: int
    revoked_count: int


class ServerPage(_Model):
    items: list[ServerView]
    next_cursor: str | None = None


class ToolList(_Model):
    server_id: str
    etag: str | None = None
    items: list[ToolView]


class SyncView(_Model):
    server: ServerView
    added: list[str]
    changed: list[str]
    revoked: list[str]
    removed: list[str]
    unchanged: list[str]
    manifest_hash: str
    synced_at: AwareDatetime


def _entry_view(entry: ToolManifestEntry) -> ToolEntryView:
    return ToolEntryView(
        name=entry.name,
        title=entry.title,
        description=entry.description,
        input_schema=entry.input_schema,
        output_schema=entry.output_schema,
        annotations=entry.annotations,
        tool_hash=entry.tool_hash,
    )


def _change(record: ToolRecord) -> ToolChangeView | None:
    approval = record.approval
    before = record.approved_entry
    if approval.state != "revoked" or approval.revoked_reason != HASH_CHANGED or before is None:
        return None
    after = record.entry
    return ToolChangeView(
        before=_entry_view(before),
        after=_entry_view(after),
        description_changed=before.description != after.description,
        input_schema_changed=before.input_schema != after.input_schema,
        output_schema_changed=before.output_schema != after.output_schema,
    )


def tool_view(record: ToolRecord) -> ToolView:
    approval = record.approval
    return ToolView(
        name=record.name,
        state=approval.state,
        enabled=record.callable_hash is not None,
        current_hash=record.entry.tool_hash,
        approved_hash=approval.approved_hash,
        approved_by=approval.approved_by,
        approved_at=approval.approved_at,
        revoked_reason=approval.revoked_reason,
        revoked_by=approval.revoked_by,
        first_seen_at=record.first_seen_at,
        last_seen_at=record.last_seen_at,
        updated_at=approval.updated_at,
        entry=_entry_view(record.entry),
        change=_change(record),
    )


def server_view(server: RegisteredServer) -> ServerView:
    states = [t.approval.state for t in server.tools]
    return ServerView(
        id=server.id,
        url=server.url,
        host=server.host,
        display_name=server.display_name,
        cloud=server.cloud.value,
        status=server.status,
        registered_by=server.registered_by,
        registered_at=server.registered_at,
        last_synced_at=server.last_synced_at,
        manifest_hash=server.manifest_hash,
        etag=server.etag,
        tool_count=len(states),
        pending_count=states.count("pending"),
        approved_count=states.count("approved"),
        revoked_count=states.count("revoked"),
    )


def tool_list(server: RegisteredServer) -> ToolList:
    tools = sorted(server.tools, key=lambda t: t.name)
    return ToolList(server_id=server.id, etag=server.etag, items=[tool_view(t) for t in tools])


def sync_view(server: RegisteredServer, result: SyncResult) -> SyncView:
    return SyncView(
        server=server_view(server),
        added=list(result.added),
        changed=list(result.changed),
        revoked=list(result.revoked),
        removed=list(result.removed),
        unchanged=list(result.unchanged),
        manifest_hash=result.manifest_hash,
        synced_at=result.synced_at,
    )
