"""First-run checklist derived from the composition registry (PRP-45 item 2).

The same ``ComponentRegistry`` ``/readyz`` reads (``app.state.composition``), plus the stored
settings snapshot, the composed write-target registry and the customer binding. Item ids are
stable and listed in ``docs/runbooks/system-settings.md``:

=================================  ===================  =========================================
item id                            component            complete when
=================================  ===================  =========================================
``optional.<component>``           each optional one    the component is ``ok``
``ingest.producers``               ``ingest``           ingestion is composed with producers
``write_targets.registered``       ``write_targets``    a write connector is registered
``stored_settings.store``          ``admin_config``     the stored-settings read succeeded
``auth.customer_binding``          ``authz``            ``NS_AUTH_CUSTOMER_ID`` is set
=================================  ===================  =========================================

Statuses are the contract's (``complete | missing | disabled | not_applicable | error``); every
status but ``complete`` carries a reason code, never a value.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Final

from neurosphere_contracts.admin.v1.first_run_checklist_item import FirstRunChecklistItem
from neurosphere_core.admin.runtime import StoredSettingsSnapshot

from neurosphere_api.runtime.status import ComponentRegistry, ComponentStatus

__all__ = ["RUNBOOK", "build_checklist", "checklist_item_ids"]

RUNBOOK: Final = "docs/runbooks/system-settings.md"
_SCHEMA: Final = "1.0.0"


def _item(
    item_id: str, component: str, status: str, reason: str | None, anchor: str, *, required: bool
) -> FirstRunChecklistItem:
    return FirstRunChecklistItem.model_validate(
        {
            "schema_version": _SCHEMA,
            "item_id": item_id,
            "component": component,
            "status": status,
            "reason": None if status == "complete" else reason,
            "doc_path": f"{RUNBOOK}#{anchor}",
            "required": required,
        }
    )


def _from_component(status: ComponentStatus, item_id: str, anchor: str) -> FirstRunChecklistItem:
    if status.state == "ok":
        return _item(item_id, status.name, "complete", None, anchor, required=status.required)
    if status.state == "disabled":
        return _item(item_id, status.name, "disabled", "component_disabled", anchor, required=False)
    if status.state == "failed":
        reason = status.reason or "failed"
        return _item(item_id, status.name, "error", reason, anchor, required=status.required)
    return _item(item_id, status.name, "missing", "not_built", anchor, required=status.required)


def _optional(registry: ComponentRegistry) -> Iterable[FirstRunChecklistItem]:
    for status in registry.snapshot():
        if not status.required and not status.step:
            yield _from_component(status, f"optional.{status.name}", "optional-components")


def _ingest(registry: ComponentRegistry) -> FirstRunChecklistItem:
    item = _from_component(registry.get("ingest"), "ingest.producers", "ingest-producers")
    if item.status == "disabled":
        return _item(
            "ingest.producers",
            "ingest",
            "missing",
            "ingest_producers_unconfigured",
            "ingest-producers",
            required=False,
        )
    return item


def _write_targets(
    registered: Iterable[str], snapshot: StoredSettingsSnapshot
) -> FirstRunChecklistItem:
    anchor = "write-targets"
    if tuple(registered):
        return _item(
            "write_targets.registered", "write_targets", "complete", None, anchor, required=False
        )
    if snapshot.write_targets:
        return _item(
            "write_targets.registered",
            "write_targets",
            "disabled",
            "write_targets_stored_not_registered",
            anchor,
            required=False,
        )
    return _item(
        "write_targets.registered",
        "write_targets",
        "missing",
        "write_targets_unconfigured",
        anchor,
        required=False,
    )


def _store(snapshot: StoredSettingsSnapshot) -> FirstRunChecklistItem:
    anchor = "stored-settings-store"
    if snapshot.status == "loaded":
        return _item(
            "stored_settings.store", "admin_config", "complete", None, anchor, required=False
        )
    status = "error" if snapshot.status == "unavailable" else "missing"
    reason = snapshot.reason or "stored_settings_unavailable"
    return _item("stored_settings.store", "admin_config", status, reason, anchor, required=False)


def _binding(binding: str) -> FirstRunChecklistItem:
    anchor = "customer-binding"
    if binding == "explicit":
        return _item("auth.customer_binding", "authz", "complete", None, anchor, required=True)
    if binding == "local_default":
        return _item(
            "auth.customer_binding",
            "authz",
            "not_applicable",
            "local_default_customer",
            anchor,
            required=True,
        )
    return _item(
        "auth.customer_binding", "authz", "missing", "customer_id_missing", anchor, required=True
    )


def build_checklist(
    registry: ComponentRegistry,
    snapshot: StoredSettingsSnapshot,
    *,
    registered_write_targets: Iterable[str],
    customer_binding: str,
) -> list[FirstRunChecklistItem]:
    return [
        *_optional(registry),
        _ingest(registry),
        _write_targets(registered_write_targets, snapshot),
        _store(snapshot),
        _binding(customer_binding),
    ]


def checklist_item_ids(registry: ComponentRegistry) -> tuple[str, ...]:
    """Every item id in order (the runbook lists them; a test pins the list)."""
    empty = StoredSettingsSnapshot.empty("unconfigured", "stored_settings_unconfigured")
    items = build_checklist(
        registry, empty, registered_write_targets=(), customer_binding="missing"
    )
    return tuple(i.item_id.root for i in items)
