"""The removal guard, the removal plan and the only deletion path.

``assert_removable`` is the single decision point. ``plan_removal`` and ``remove`` call it for
every row; ``remove`` is the only caller of ``ResourceDeleter.delete`` and it calls the guard
immediately before. Tags are never inputs. A resource absent from the register is never in a
plan. No network calls here: deletion is an injected ``ResourceDeleter``.
"""

from __future__ import annotations

import re
from collections.abc import Collection, Iterable, Mapping, Sequence
from enum import StrEnum
from typing import Final, Protocol

from pydantic import BaseModel, ConfigDict

from neurosphere_core.deploy.register.models import (
    CREATED_BY_NEUROSPHERE,
    Ownership,
    ResourceRow,
    normalize_id,
)
from neurosphere_core.errors import ForbiddenError

_RESOURCE_GROUP: Final = re.compile(r"^/subscriptions/[^/]+/resourcegroups/[^/]+$")


class ResourceDeleter(Protocol):
    async def delete(self, resource_id: str) -> None: ...


class LiveInventory(Protocol):
    """Lists the live resource ids inside a resource group (ARM ``/resources``), network-side."""

    async def list_resource_group(self, rg_id: str) -> list[str]: ...


DRY_RUN_UNVERIFIED: Final = "live contents not verified (dry-run)"


def is_resource_group(resource_id: str) -> bool:
    return _RESOURCE_GROUP.fullmatch(normalize_id(resource_id)) is not None


def foreign_live_ids(live_ids: Iterable[str], register: Sequence[ResourceRow]) -> list[str]:
    """Live ids that are not ``created`` rows in the register."""
    created = _created_ids(register)
    return sorted({i for i in live_ids if normalize_id(i) not in created})


async def assert_resource_group_empty_of_foreign(
    rg_id: str, register: Sequence[ResourceRow], inventory: LiveInventory
) -> None:
    """Fail closed: refuse unless the RG's live contents are all registered ``created`` rows.

    A listing failure is a refusal, never a pass: deletion on an unknown is not allowed.
    """
    try:
        live = await inventory.list_resource_group(rg_id)
    except Exception as exc:
        raise ForbiddenError(
            f"cannot verify live contents of {rg_id}; refusing to delete the resource group"
        ) from exc
    foreign = foreign_live_ids(live, register)
    if foreign:
        raise ForbiddenError(
            f"resource group {rg_id} contains live resources not created by NeuroSphere: "
            + ", ".join(foreign)
        )


def _created_ids(register: Iterable[ResourceRow]) -> set[str]:
    return {
        normalize_id(r.resource_id)
        for r in register
        if r.ownership is Ownership.CREATED and r.created_by == CREATED_BY_NEUROSPHERE
    }


def assert_removable(row: ResourceRow, register: Sequence[ResourceRow]) -> None:
    """Raise ``ForbiddenError`` unless ``row`` is a NeuroSphere-created, dependent-free resource.

    ``register`` is the full set of rows for the deployment: a dependent is foreign unless it is
    recorded there as ``created``. A resource group is removable only if every registered row
    inside it is also created.
    """
    if row.ownership is not Ownership.CREATED:
        raise ForbiddenError(f"{row.ownership.value} resources are never removed")
    if row.created_by != CREATED_BY_NEUROSPHERE:
        raise ForbiddenError("resource was not created by NeuroSphere")
    created = _created_ids(register)
    rid = normalize_id(row.resource_id)
    if rid not in created:
        raise ForbiddenError("resource is not recorded as created in the register")
    if any(normalize_id(d) not in created for d in row.dependents):
        raise ForbiddenError("resource has foreign dependents")
    if _RESOURCE_GROUP.fullmatch(rid):
        for other in register:
            oid = normalize_id(other.resource_id)
            if oid.startswith(rid + "/") and oid not in created:
                raise ForbiddenError("resource group contains resources not created by NeuroSphere")


class Action(StrEnum):
    UNTOUCHED = "untouched"
    REMOVABLE = "removable"


class PlanEntry(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    resource_id: str
    service: str | None
    ownership: str | None
    action: Action
    reason: str | None = None
    order: int | None = None


class RemovalPlan(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    deployment_id: str
    entries: tuple[PlanEntry, ...]

    @property
    def removable(self) -> tuple[PlanEntry, ...]:
        found = [e for e in self.entries if e.action is Action.REMOVABLE]
        return tuple(sorted(found, key=lambda e: e.order if e.order is not None else 0))


def _removal_order(candidates: dict[str, ResourceRow], reasons: dict[str, str]) -> list[str]:
    """Kahn ordering: a resource is deleted after all of its dependents."""
    remaining = {k: {normalize_id(d) for d in row.dependents} for k, row in candidates.items()}
    order: list[str] = []
    while remaining:
        ready = sorted(k for k, deps in remaining.items() if not deps)
        if not ready:
            for key in remaining:
                reasons[key] = "dependency cycle"
            break
        for key in ready:
            order.append(key)
            del remaining[key]
        for deps in remaining.values():
            deps.difference_update(ready)
    return order


def plan_removal(
    deployment_id: str,
    rows: Sequence[ResourceRow],
    *,
    unregistered_ids: Collection[str] = (),
    live_contents: Mapping[str, Collection[str]] | None = None,
) -> RemovalPlan:
    """Classify every row; removable rows are ordered dependents-first.

    ``unregistered_ids`` (e.g. discovered resources) are reported untouched, never removable.
    ``live_contents`` maps a resource group id to its live resource ids; a group holding any live
    resource that is not a ``created`` row is untouched. Without it, removable groups are labelled
    as not live-verified.
    """
    by_id = {normalize_id(r.resource_id): r for r in rows}
    reasons: dict[str, str] = {}
    candidates: dict[str, ResourceRow] = {}
    for key, row in by_id.items():
        try:
            assert_removable(row, rows)
        except ForbiddenError as exc:
            reasons[key] = exc.detail or exc.title
        else:
            candidates[key] = row
    live = {normalize_id(k): v for k, v in (live_contents or {}).items()}
    for key in list(candidates):
        if not is_resource_group(key) or key not in live:
            continue
        foreign = foreign_live_ids(live[key], rows)
        if foreign:
            reasons[key] = "live resource group contains resources not created by NeuroSphere: " + (
                ", ".join(foreign)
            )
            del candidates[key]
    # A created dependent that is itself blocked still exists, so what it needs stays too.
    changed = True
    while changed:
        changed = False
        for key in list(candidates):
            if any(normalize_id(d) not in candidates for d in candidates[key].dependents):
                reasons[key] = "a dependent resource is not removable"
                del candidates[key]
                changed = True
    order = _removal_order(candidates, reasons)
    # Resource groups always go last, after every child.
    order = [k for k in order if not is_resource_group(k)] + [
        k for k in order if is_resource_group(k)
    ]
    position = {k: i for i, k in enumerate(order)}
    entries: list[PlanEntry] = []
    for key, row in by_id.items():
        removable = key in position
        entries.append(
            PlanEntry(
                resource_id=row.resource_id,
                service=row.service,
                ownership=row.ownership.value,
                action=Action.REMOVABLE if removable else Action.UNTOUCHED,
                reason=(
                    (DRY_RUN_UNVERIFIED if is_resource_group(key) and key not in live else None)
                    if removable
                    else reasons.get(key, "not removable")
                ),
                order=position.get(key),
            )
        )
    for extra in unregistered_ids:
        if normalize_id(extra) not in by_id:
            entries.append(
                PlanEntry(
                    resource_id=extra,
                    service=None,
                    ownership=None,
                    action=Action.UNTOUCHED,
                    reason="not in the ownership register",
                )
            )
    entries.sort(key=lambda e: (e.action is Action.REMOVABLE, e.order or 0, e.resource_id.lower()))
    return RemovalPlan(deployment_id=deployment_id, entries=tuple(entries))


async def remove(
    deployment_id: str,
    rows: Sequence[ResourceRow],
    deleter: ResourceDeleter,
    inventory: LiveInventory | None = None,
) -> list[str]:
    """Delete removable rows in order, re-running the guard before every call.

    Resource groups are deleted last and only after their live contents are verified against the
    register through ``inventory``; a plan containing a resource group is refused outright without
    one. All groups are verified before the first delete, and each is re-verified immediately
    before its own delete. Returns the resource ids deleted. This function is the only caller of
    ``deleter.delete``.
    """
    plan = plan_removal(deployment_id, rows)
    by_id = {normalize_id(r.resource_id): r for r in rows}
    groups = [e for e in plan.removable if is_resource_group(e.resource_id)]
    if groups and inventory is None:
        raise ForbiddenError("a live inventory is required to remove a resource group")
    if inventory is not None:
        for group in groups:
            await assert_resource_group_empty_of_foreign(group.resource_id, rows, inventory)
    deleted: list[str] = []
    for entry in plan.removable:
        row = by_id[normalize_id(entry.resource_id)]
        assert_removable(row, rows)
        if is_resource_group(row.resource_id):
            if inventory is None:
                raise ForbiddenError("a live inventory is required to remove a resource group")
            await assert_resource_group_empty_of_foreign(row.resource_id, rows, inventory)
        await deleter.delete(row.resource_id)
        deleted.append(row.resource_id)
    return deleted
