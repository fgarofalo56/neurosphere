"""Registration rules and the pure state transitions of the MCP server registry.

Everything here is deterministic and store-free; :mod:`neurosphere_core.mcp.store` applies the
transitions under an ETag so every store implementation behaves identically.

Sync semantics (clarification 11):

* a tool the server newly advertises starts ``pending`` (disabled);
* an unchanged ``tool_hash`` keeps its state;
* a changed hash revokes an approval (``revoked``, reason ``hash_changed``) while keeping the
  previously approved hash and entry for the administrator's diff; a pending tool stays pending
  with the new entry;
* a tool that vanished becomes ``removed``; if it reappears it is ``pending`` again.

Callability is decided at call time by :func:`check_callable`: the server is active, the tool is
``approved``, and the approved hash equals both the stored latest entry and the LIVE hash the
server advertises right now.
"""

from __future__ import annotations

import ipaddress
from datetime import datetime

from pydantic import ValidationError

from neurosphere_core.audit.canonical import digests_equal
from neurosphere_core.errors import ValidationIssue
from neurosphere_core.mcp.errors import (
    CLOUD_BOUNDARY_MISMATCH,
    INVALID_REGISTRATION,
    MCP_SERVER_DISABLED,
    OUTSIDE_GOVERNMENT_BOUNDARY,
    SSRF_BLOCKED_ADDRESS,
    TOOL_HASH_CHANGED,
    TOOL_HASH_MISMATCH,
    TOOL_NOT_APPROVABLE,
    TOOL_NOT_APPROVED,
    TOOL_NOT_FOUND,
    forbidden,
    invalid,
    stale,
)
from neurosphere_core.mcp.manifest import ValidatedManifest
from neurosphere_core.mcp.models import (
    McpClientPolicy,
    RegisteredServer,
    SyncResult,
    ToolApproval,
    ToolRecord,
)
from neurosphere_core.mcp.ssrf import blocked_address_reason
from neurosphere_core.mcp.urls import (
    ServerUrl,
    check_hostname_allowed,
    normalize_server_url,
    server_id_for,
)

__all__ = [
    "HASH_CHANGED",
    "apply_approval",
    "apply_revocation",
    "apply_sync",
    "check_boundary",
    "check_callable",
    "new_registration",
]

HASH_CHANGED = "hash_changed"


def check_boundary(url: ServerUrl, policy: McpClientPolicy) -> None:
    """Refuse a Government-deployment target outside the approved boundary (``forbidden``)."""
    if not policy.host_in_boundary(url.host, ip_literal=url.ip_literal):
        raise forbidden(
            OUTSIDE_GOVERNMENT_BOUNDARY,
            "server host is outside the approved Government boundary",
        )


def new_registration(
    raw_url: str,
    *,
    display_name: str,
    actor: str,
    policy: McpClientPolicy,
    now: datetime,
) -> RegisteredServer:
    """Validate an administrator's registration request and build the record (not stored).

    Exact HTTPS URL (``invalid_schema`` otherwise), not a blocked hostname or a blocked IP
    literal (``forbidden``), and inside the Government boundary when the deployment is
    Government (``forbidden``). DNS is NOT consulted here: addresses are vetted on every
    connection, because a registration-time answer proves nothing about the next lookup.
    """
    url = normalize_server_url(raw_url)
    check_hostname_allowed(url)
    if url.ip_literal:
        reason = blocked_address_reason(ipaddress.ip_address(url.host))
        if reason is not None:
            raise forbidden(
                SSRF_BLOCKED_ADDRESS, f"server address is in a blocked range ({reason})"
            )
    check_boundary(url, policy)
    if any(ord(ch) < 0x20 or ord(ch) == 0x7F for ch in display_name):
        raise invalid(INVALID_REGISTRATION, "display_name must not contain control characters")
    try:
        return RegisteredServer(
            id=server_id_for(url),
            url=url.url,
            host=url.host,
            port=url.port,
            display_name=display_name.strip(),
            cloud=policy.cloud,
            registered_by=actor,
            registered_at=now,
        )
    except ValidationError as exc:
        issues = [
            ValidationIssue("/" + "/".join(str(p) for p in e["loc"]), e["msg"])
            for e in exc.errors(include_input=False)
        ]
        raise invalid(INVALID_REGISTRATION, "registration is not valid", issues=issues) from None


def _pending(now: datetime, previous: ToolApproval | None = None) -> ToolApproval:
    return ToolApproval(
        state="pending",
        approved_hash=previous.approved_hash if previous else None,
        approved_by=previous.approved_by if previous else None,
        approved_at=previous.approved_at if previous else None,
        updated_at=now,
    )


def apply_sync(
    server: RegisteredServer, manifest: ValidatedManifest, *, now: datetime
) -> tuple[RegisteredServer, SyncResult]:
    """Apply a validated live manifest to ``server`` (see module docstring)."""
    live = manifest.by_name()
    existing = {t.name: t for t in server.tools}
    added: list[str] = []
    changed: list[str] = []
    revoked: list[str] = []
    removed: list[str] = []
    unchanged: list[str] = []
    records: list[ToolRecord] = []
    for name in sorted(set(live) | set(existing)):
        entry = live.get(name)
        record = existing.get(name)
        if record is None:
            assert entry is not None
            added.append(name)
            records.append(
                ToolRecord(
                    name=name,
                    entry=entry,
                    approval=_pending(now),
                    first_seen_at=now,
                    last_seen_at=now,
                )
            )
            continue
        if entry is None:
            if record.approval.state != "removed":
                removed.append(name)
                approval = record.approval.model_copy(
                    update={"state": "removed", "updated_at": now}
                )
                record = record.model_copy(update={"approval": approval})
            records.append(record)
            continue
        same = digests_equal(entry.tool_hash, record.entry.tool_hash)
        state = record.approval.state
        if state == "removed":
            added.append(name)
            approval = _pending(now, record.approval)
        elif same:
            unchanged.append(name)
            approval = record.approval
        else:
            changed.append(name)
            if state == "approved":
                revoked.append(name)
                approval = record.approval.model_copy(
                    update={
                        "state": "revoked",
                        "revoked_reason": HASH_CHANGED,
                        "revoked_by": None,
                        "updated_at": now,
                    }
                )
            else:
                approval = record.approval.model_copy(update={"updated_at": now})
        records.append(
            record.model_copy(update={"entry": entry, "approval": approval, "last_seen_at": now})
        )
    updated = server.model_copy(
        update={
            "tools": tuple(records),
            "last_synced_at": now,
            "manifest_hash": manifest.manifest_hash,
        }
    )
    result = SyncResult(
        server_id=server.id,
        synced_at=now,
        manifest_hash=manifest.manifest_hash,
        added=tuple(added),
        changed=tuple(changed),
        revoked=tuple(revoked),
        removed=tuple(removed),
        unchanged=tuple(unchanged),
    )
    return RegisteredServer.model_validate(updated.model_dump()), result


def _replace_tool(server: RegisteredServer, record: ToolRecord) -> RegisteredServer:
    tools = tuple(record if t.name == record.name else t for t in server.tools)
    return RegisteredServer.model_validate(server.model_copy(update={"tools": tools}).model_dump())


def _record(server: RegisteredServer, tool_name: str) -> ToolRecord:
    record = server.tool(tool_name)
    if record is None:
        raise invalid(TOOL_NOT_FOUND, "the server has not advertised that tool")
    return record


def apply_approval(
    server: RegisteredServer,
    tool_name: str,
    *,
    expected_hash: str,
    actor: str,
    now: datetime,
) -> RegisteredServer:
    """Approve exactly the entry the administrator reviewed (``expected_hash``).

    A removed tool is not approvable (``invalid_schema`` ``tool_not_approvable``); an
    ``expected_hash`` that is no longer the latest entry raises ``stale_version``
    ``tool_hash_changed`` so a reviewer never approves content they did not see.
    """
    record = _record(server, tool_name)
    if record.approval.state == "removed":
        raise invalid(TOOL_NOT_APPROVABLE, "a removed tool cannot be approved")
    if not digests_equal(record.entry.tool_hash, expected_hash):
        raise stale(TOOL_HASH_CHANGED, "the tool changed since it was reviewed")
    approval = ToolApproval(
        state="approved",
        approved_hash=record.entry.tool_hash,
        approved_by=actor,
        approved_at=now,
        updated_at=now,
    )
    return _replace_tool(
        server, record.model_copy(update={"approval": approval, "approved_entry": record.entry})
    )


def apply_revocation(
    server: RegisteredServer,
    tool_name: str,
    *,
    actor: str,
    reason: str,
    now: datetime,
) -> RegisteredServer:
    """Revoke (or deny a pending) tool. The previously approved hash and entry are kept."""
    record = _record(server, tool_name)
    if record.approval.state == "removed":
        raise invalid(TOOL_NOT_APPROVABLE, "a removed tool cannot be revoked")
    approval = ToolApproval(
        state="revoked",
        approved_hash=record.approval.approved_hash,
        approved_by=record.approval.approved_by,
        approved_at=record.approval.approved_at,
        revoked_reason=reason,
        revoked_by=actor,
        updated_at=now,
    )
    return _replace_tool(server, record.model_copy(update={"approval": approval}))


def check_callable(
    server: RegisteredServer,
    tool_name: str,
    *,
    live_hash: str | None,
    policy: McpClientPolicy,
) -> ToolRecord:
    """The record of a tool that may be called now, else ``forbidden``.

    ``live_hash`` is the hash of the entry the server advertises in the CURRENT session
    (``None`` when it no longer lists the tool).
    """
    if server.status != "active":
        raise forbidden(MCP_SERVER_DISABLED, "the server is disabled")
    if server.cloud is not policy.cloud:
        raise forbidden(CLOUD_BOUNDARY_MISMATCH, "the server is registered for another cloud")
    check_boundary(normalize_server_url(server.url), policy)
    record = server.tool(tool_name)
    if record is None or record.callable_hash is None:
        raise forbidden(TOOL_NOT_APPROVED, "the tool is not approved")
    if live_hash is None or not digests_equal(record.callable_hash, live_hash):
        raise forbidden(TOOL_HASH_MISMATCH, "the tool changed since it was approved")
    return record
