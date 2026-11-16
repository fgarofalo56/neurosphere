"""Stored runtime settings routes, at ``/api/v1/admin/system/settings`` (PRP-45 item 3).

| Method | Path        | Notes                                                                 |
|--------|-------------|-----------------------------------------------------------------------|
| GET    | ``""``      | the six keys: source, stored/applied revision, ``restart_required``  |
| GET    | ``/{key}``  | one key with its stored entries (``ETag`` for a single-document key)  |
| PUT    | ``/{key}``  | store a ``SystemSetting``; ``If-Match`` required; returns the diff    |

Concurrency (the catalog convention): a missing ``If-Match`` is ``invalid_schema``
(``if_match_required``), a stale one ``stale_version``. When nothing is stored yet the ``ETag`` is
:data:`ABSENT_ETAG`; sending it creates the document, and fails ``stale_version`` once one exists.
``write_targets`` holds one document per ``target_kind``; ``If-Match`` names that entry's ETag.

Validation runs ``validate_setting`` (credential-shaped names, cross-cloud endpoints, references
only) and then builds the settings class the runtime builder uses from the stored fields, so a
value the builder would refuse is refused here (422, nothing stored). Stored values apply at the
next start (A1): ``restart_required`` turns true until then. Stored ``write_targets`` entries are
validated and listed but NOT registered (PRP-54).

No ``from __future__ import annotations``: FastAPI inspects these signatures.
"""

from collections.abc import Iterator, Mapping
from typing import Annotated, Any, Final

from fastapi import APIRouter, Body, Depends, Path, Request, Response
from neurosphere_contracts.admin.v1.admin_config_document import AdminConfigDocument
from neurosphere_contracts.admin.v1.system_setting import SystemSetting
from neurosphere_core.admin.runtime import (
    SETTING_KEYS,
    SYSTEM_SETTING_KIND,
    WRITE_TARGETS,
    SettingKey,
    copilot_init_args,
    document_id,
    judge_init_args,
    key_of_document,
    mcp_server_init_args,
    revision_of,
    scan_init_args,
    search_init_args,
    validate_setting,
)
from neurosphere_core.errors import InvalidSchemaError, StaleVersionError, ValidationIssue
from neurosphere_core.scope import IdentityScope
from pydantic import ValidationError

from neurosphere_api.admin.system.deps import AdminScope, IfMatch, correlation, set_etag
from neurosphere_api.admin.system.models import (
    DiffEntry,
    SettingEntry,
    SettingsPage,
    SettingView,
    SettingWriteResult,
)
from neurosphere_api.admin.system.router import stored_state
from neurosphere_api.admin.system.service import SystemAdminPlane, SystemAuditor, get_plane
from neurosphere_api.admin.system.stored import setting_source

__all__ = ["ABSENT_ETAG", "build_router", "check_runtime_settings"]

#: ``ETag`` of a key (or write-target kind) with nothing stored; ``If-Match`` it to create.
ABSENT_ETAG: Final = '"absent"'

Plane = Annotated[SystemAdminPlane, Depends(get_plane)]
KeyPath = Annotated[str, Path(pattern=r"^[a-z_]{1,32}$")]


def _refuse(pointer: str, detail: str, reason: str) -> InvalidSchemaError:
    return InvalidSchemaError(
        "runtime setting is invalid", errors=[ValidationIssue(pointer, detail)], reason=reason
    )


def _key(value: str) -> SettingKey:
    if value not in SETTING_KEYS:
        raise _refuse("/key", "unknown setting key", "unknown_setting_key")
    return value  # type: ignore[return-value]


def check_runtime_settings(key: SettingKey, setting: SystemSetting, cloud: str) -> None:
    """Build the runtime settings class from the stored fields; refuse what the builder would."""
    from neurosphere_api.deploy.scan.settings import ScanSettings
    from neurosphere_api.mcp.server.settings import McpServerSettings
    from neurosphere_api.runtime.builders.copilot import CopilotRuntimeSettings
    from neurosphere_api.runtime.builders.search import SearchSettings

    try:
        if key == "copilot":
            try:
                env_mode = CopilotRuntimeSettings().mode
            except ValidationError:
                env_mode = "disabled"
            CopilotRuntimeSettings(**copilot_init_args(setting, env_mode=env_mode))
        elif key == "search":
            SearchSettings(**search_init_args(setting, cloud=cloud))  # type: ignore[arg-type]
        elif key == "mcp_server":
            args = mcp_server_init_args(setting)
            if args is not None:
                McpServerSettings(**args)
        elif key == "scan":
            ScanSettings(**scan_init_args(setting))
        elif key == "judge":
            from neurosphere_workers.runtime.settings import EvalSettings

            EvalSettings(**judge_init_args(setting))
    except ValidationError:
        reason = f"{key}_settings_invalid"
        raise _refuse(f"/body/{key}", "refused by the runtime settings", reason) from None


def _entry(document: AdminConfigDocument) -> SettingEntry:
    return SettingEntry(
        document_id=document.id.root,
        version=document.version.root,
        etag=document.etag.root,
        value=document.body.model_dump(mode="json"),
    )


async def _documents(plane: SystemAdminPlane, customer: str) -> list[AdminConfigDocument]:
    return await plane.repository.list_by_kind(customer, SYSTEM_SETTING_KIND, limit=1000)


def _view(key: SettingKey, plane: SystemAdminPlane, docs: list[AdminConfigDocument]) -> SettingView:
    mine = [d for d in docs if d.status == "active" and key_of_document(d.id.root) == key]
    stored = revision_of(key, mine)
    applied = plane.applied.revision(key)
    runtime = key != WRITE_TARGETS
    etag: str | None = None
    if runtime:
        etag = mine[0].etag.root if mine else ABSENT_ETAG
    return SettingView(
        key=key,
        source=setting_source(key, plane.applied, plane.environ),
        stored_revision=stored,
        applied_revision=applied,
        restart_required=runtime and stored != applied,
        applied_by_runtime=runtime,
        etag=etag,
        entries=[_entry(d) for d in sorted(mine, key=lambda d: d.id.root)],
    )


def _flatten(node: Any, pointer: str = "") -> Iterator[tuple[str, Any]]:
    if isinstance(node, Mapping) and node:
        for name, value in node.items():
            yield from _flatten(value, f"{pointer}/{name}")
    elif isinstance(node, list) and node:
        for index, value in enumerate(node):
            yield from _flatten(value, f"{pointer}/{index}")
    else:
        yield pointer or "/", node


def diff_bodies(before: Mapping[str, Any] | None, after: Mapping[str, Any]) -> list[DiffEntry]:
    old = dict(_flatten(before)) if before is not None else {}
    new = dict(_flatten(after))
    return [
        DiffEntry(pointer=p, before=old.get(p), after=new.get(p))
        for p in sorted(old.keys() | new.keys())
        if old.get(p) != new.get(p) or (p in old) != (p in new)
    ]


async def _write(
    plane: SystemAdminPlane,
    scope: IdentityScope,
    key: SettingKey,
    body: Mapping[str, Any],
    if_match: str,
    correlation_id: str,
) -> tuple[AdminConfigDocument, list[DiffEntry]]:
    customer = scope.customer_id
    cloud: Any = plane.cloud
    setting = validate_setting(key, body, customer_id=customer, cloud=cloud)
    check_runtime_settings(key, setting, plane.cloud)
    target = setting.write_target.target_kind if setting.write_target is not None else None
    doc_id = document_id(key, target)
    auditor = SystemAuditor(plane, scope)
    current = await plane.repository.get(customer, SYSTEM_SETTING_KIND, doc_id)
    new_body = setting.model_dump(mode="json")
    diff = diff_bodies(None if current is None else current.body.model_dump(mode="json"), new_body)

    async def mutate() -> AdminConfigDocument:
        if if_match == ABSENT_ETAG:
            if current is not None:
                raise StaleVersionError("a value is already stored", reason="admin_config_exists")
            return await plane.repository.create(
                customer, SYSTEM_SETTING_KIND, doc_id, new_body, updated_by=auditor.actor
            )
        if current is None:
            raise StaleVersionError("nothing is stored yet", reason="admin_config_modified")
        return await plane.repository.replace(
            customer,
            SYSTEM_SETTING_KIND,
            doc_id,
            new_body,
            if_match=if_match,
            updated_by=auditor.actor,
        )

    document = await auditor.run(
        correlation_id,
        doc_id,
        mutate,
        info=lambda d: (
            d.etag.root,
            {"key": key, "version": d.version.root, "changed": [e.pointer for e in diff]},
        ),
    )
    return document, diff


def build_router() -> APIRouter:
    router = APIRouter(tags=["admin-system-settings"])

    @router.get("", response_model=SettingsPage)
    async def list_settings(scope: AdminScope, plane: Plane) -> SettingsPage:
        docs = await _documents(plane, scope.customer_id)
        return SettingsPage(
            items=[_view(k, plane, docs) for k in SETTING_KEYS],
            stored_settings=stored_state(plane.applied),
        )

    @router.get("/{key}", response_model=SettingView)
    async def get_setting(
        response: Response, key: KeyPath, scope: AdminScope, plane: Plane
    ) -> SettingView:
        view = _view(_key(key), plane, await _documents(plane, scope.customer_id))
        if view.etag is not None:
            set_etag(response, view.etag)
        return view

    @router.put("/{key}", response_model=SettingWriteResult)
    async def put_setting(
        request: Request,
        response: Response,
        key: KeyPath,
        scope: AdminScope,
        plane: Plane,
        if_match: IfMatch = None,
        body: Annotated[dict[str, Any], Body()] = ...,  # type: ignore[assignment]
    ) -> SettingWriteResult:
        setting_key = _key(key)
        if not if_match:
            raise _refuse("/headers/If-Match", "If-Match is required", "if_match_required")
        document, diff = await _write(
            plane, scope, setting_key, body, if_match, correlation(request)
        )
        docs = await _documents(plane, scope.customer_id)
        view = _view(setting_key, plane, docs)
        set_etag(response, document.etag.root)
        return SettingWriteResult(
            key=setting_key,
            document_id=document.id.root,
            version=document.version.root,
            etag=document.etag.root,
            stored_revision=view.stored_revision,
            applied_revision=view.applied_revision,
            restart_required=view.restart_required,
            diff=diff,
        )

    return router
