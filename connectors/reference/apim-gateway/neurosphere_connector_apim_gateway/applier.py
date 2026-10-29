"""Apply a reviewed ``PublishPlan`` step by step, and reverse it.

Per step: re-read existence immediately before the write; refuse to overwrite a resource the plan
expected to create (``stale_version`` reason ``resource_appeared``) and refuse a step whose found
resource vanished or drifted; update a found resource only with ``If-Match`` set to the ETag of
that read (a ``412`` surfaces as ``stale_version``); read the resource back after the write and
append the ownership record (``created`` or ``found``) to the record store before moving on.

On any failure the completed steps are reversed newest first: resources recorded ``created`` are
deleted (with the ETag recorded after our write, so a resource someone changed since is left
alone); ``found`` resources are restored to their captured prior properties, never deleted. A
reversal that fails leaves the resource in ``orphans`` and the error becomes
``capability_unavailable`` reason ``rollback_failed``. A write whose response was lost may have
reached ARM; when the failing create step's resource is present afterwards its ownership is
unknown, so it is reported as an orphan rather than deleted.

Nothing here logs payloads: log lines carry the step's type, name and ownership only.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable, Sequence
from typing import Any

from neurosphere_core.errors import (
    CapabilityUnavailableError,
    DependencyTransientError,
    StaleVersionError,
)

from neurosphere_connector_apim_gateway.arm import ApimArm, ArmResource
from neurosphere_connector_apim_gateway.compare import payload_matches
from neurosphere_connector_apim_gateway.models import (
    ApplyRecord,
    PlanStep,
    PublishPlan,
    ResourceSpec,
    StepOwnership,
    StepRecord,
)
from neurosphere_connector_apim_gateway.planner import check_plan_integrity
from neurosphere_connector_apim_gateway.records import ApplyRecordStore

__all__ = ["PlanApplier", "RollbackFailedError"]

_log = logging.getLogger(__name__)


def _new_id() -> str:
    return f"apply-{uuid.uuid4().hex}"


def _record(
    step: PlanStep,
    ownership: StepOwnership,
    *,
    wrote: bool,
    etag_after: str | None = None,
    prior: dict[str, Any] | None = None,
) -> StepRecord:
    return StepRecord(
        index=step.index,
        resource_type=step.resource_type,
        name=step.name,
        operation=step.operation,
        ownership=ownership,
        wrote=wrote,
        etag_after=etag_after,
        prior=prior,
    )


class RollbackFailedError(CapabilityUnavailableError):
    """Reversal left resources behind; ``orphans`` names them (relative ARM paths)."""

    def __init__(self, orphans: Sequence[str]) -> None:
        self.orphans = tuple(orphans)
        super().__init__(
            "rollback_failed",
            "rollback could not reverse every step; orphans: " + ", ".join(self.orphans),
        )


class PlanApplier:
    def __init__(
        self,
        arm: ApimArm,
        records: ApplyRecordStore,
        *,
        id_factory: Callable[[], str] = _new_id,
    ) -> None:
        self._arm = arm
        self._records = records
        self._new_id = id_factory

    # -- apply -----------------------------------------------------------------------------

    async def apply(self, plan: PublishPlan, specs: Sequence[ResourceSpec]) -> ApplyRecord:
        bound = check_plan_integrity(plan, specs)
        record = ApplyRecord(
            id=self._new_id(),
            gateway_id=plan.gateway_id,
            target=plan.target,
            plan_digest=plan.digest,
            status="applying",
        )
        await self._records.append(record)
        done: list[StepRecord] = []
        for step in plan.steps:
            try:
                done.append(await self._apply_step(step, bound[step.index]))
            except Exception as cause:
                orphans = await self._unknown_write(step, cause)
                orphans += await self._reverse(done)
                status = "rollback_failed" if orphans else "rolled_back"
                await self._records.append(
                    record.model_copy(
                        update={"steps": tuple(done), "status": status, "orphans": tuple(orphans)}
                    )
                )
                _log.warning(
                    "apim apply failed at step %d (%s); reversed=%s orphans=%d",
                    step.index,
                    step.resource_type.value,
                    status,
                    len(orphans),
                )
                if orphans:
                    raise RollbackFailedError(orphans) from cause
                raise
            record = record.model_copy(update={"steps": tuple(done)})
            await self._records.append(record)
        record = record.model_copy(update={"status": "succeeded"})
        await self._records.append(record)
        return record

    async def _read_back(self, name: str) -> ArmResource:
        after = await self._arm.get(name)
        if after is None:
            raise DependencyTransientError(
                "the write is not visible on read-back", reason="write_not_visible"
            )
        return after

    async def _apply_step(self, step: PlanStep, spec: ResourceSpec) -> StepRecord:
        current = await self._arm.get(step.name)
        if step.operation == "delete":
            if current is None:
                raise StaleVersionError("a resource to delete vanished", reason="resource_vanished")
            if not current.etag:
                raise StaleVersionError("no ETag to guard the delete", reason="etag_unavailable")
            await self._arm.delete(step.name, if_match=current.etag)
            rec = _record(step, StepOwnership.FOUND, wrote=True, prior=current.properties)
        elif step.expected == "create":
            if current is not None:
                # Never overwrite a resource this run did not create.
                raise StaleVersionError(
                    "a resource the plan expected to create already exists",
                    reason="resource_appeared",
                )
            await self._arm.put(step.name, spec.payload or {}, if_match=None)
            after = await self._read_back(step.name)
            rec = _record(step, StepOwnership.CREATED, wrote=True, etag_after=after.etag)
        else:
            if current is None:
                raise StaleVersionError("a found resource vanished", reason="resource_vanished")
            payload = spec.payload or {}
            if not step.changes:
                if not payload_matches(step.resource_type, payload, current.properties):
                    raise StaleVersionError("a found resource drifted", reason="resource_changed")
                rec = _record(step, StepOwnership.FOUND, wrote=False, etag_after=current.etag)
            else:
                if not current.etag:
                    raise StaleVersionError(
                        "no ETag to guard the update", reason="etag_unavailable"
                    )
                await self._arm.put(step.name, payload, if_match=current.etag)
                after = await self._read_back(step.name)
                rec = _record(
                    step,
                    StepOwnership.FOUND,
                    wrote=True,
                    etag_after=after.etag,
                    prior=current.properties,
                )
        _log.info(
            "apim step %d %s %s ownership=%s wrote=%s",
            step.index,
            step.operation,
            step.resource_type.value,
            rec.ownership.value,
            rec.wrote,
        )
        return rec

    async def _unknown_write(self, step: PlanStep, cause: Exception) -> list[str]:
        """A create whose response was lost may exist now; its ownership is unknown."""
        if step.operation != "upsert" or step.expected != "create":
            return []
        if isinstance(cause, StaleVersionError):
            return []
        try:
            present = await self._arm.get(step.name)
        except Exception:
            return [step.name]
        return [step.name] if present is not None else []

    # -- reverse ---------------------------------------------------------------------------

    async def _reverse(self, done: Sequence[StepRecord]) -> list[str]:
        orphans: list[str] = []
        for rec in reversed(done):
            if not rec.wrote:
                continue
            try:
                await self._reverse_step(rec)
            except Exception:
                orphans.append(rec.name)
        return orphans

    async def _reverse_step(self, rec: StepRecord) -> None:
        if rec.operation == "delete":
            # We removed a found resource: recreate it from the captured properties.
            await self._arm.put(rec.name, rec.prior or {}, if_match=None)
            return
        if rec.ownership is StepOwnership.CREATED:
            if not rec.etag_after:
                raise StaleVersionError("no ETag recorded for a created resource")
            # Only what this run created is ever deleted, and only if unchanged since.
            await self._arm.delete(rec.name, if_match=rec.etag_after)
            return
        if not rec.etag_after:
            raise StaleVersionError("no ETag recorded for an updated resource")
        await self._arm.put(rec.name, rec.prior or {}, if_match=rec.etag_after)

    async def reverse(self, record: ApplyRecord) -> ApplyRecord:
        """Reverse a succeeded apply (the reverse plan). Raises ``RollbackFailedError``."""
        if record.status != "succeeded":
            raise CapabilityUnavailableError(
                "rollback_not_applicable", f"apply record status is {record.status}"
            )
        orphans = await self._reverse(record.steps)
        status = "rollback_failed" if orphans else "rolled_back"
        final = record.model_copy(update={"status": status, "orphans": tuple(orphans)})
        await self._records.append(final)
        _log.info("apim rollback %s orphans=%d", status, len(orphans))
        if orphans:
            raise RollbackFailedError(orphans)
        return final
