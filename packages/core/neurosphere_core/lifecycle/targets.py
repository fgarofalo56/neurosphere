"""Target, hold, queue and mapping protocols. The engine only ever talks to these."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict

from neurosphere_core.audit.builders import AuditContext
from neurosphere_core.errors import InvalidSchemaError
from neurosphere_core.lifecycle.models import (
    LegalHold,
    LifecycleRequest,
    Rule,
    TargetRecord,
)
from neurosphere_core.lifecycle.rules import is_audit_container


@runtime_checkable
class LifecycleTarget(Protocol):
    """One store's lifecycle surface. Adapters implement this over their own store."""

    target_kind: str
    container: str

    async def get(self, record_id: str) -> TargetRecord | None:
        """Metadata for a record, or ``None`` when it does not exist (the read-back)."""
        ...

    async def list_records(
        self, *, data_class: str, limit: int, after: str | None
    ) -> list[TargetRecord]:
        """Bounded page of records of ``data_class`` ordered by record id, after ``after``."""
        ...

    async def list_by_subject(
        self, subject_id: str, *, limit: int, after: str | None
    ) -> list[TargetRecord]:
        """Bounded page of records belonging to ``subject_id`` ordered by record id.

        Used to check legal holds before a subject erasure. A target that cannot enumerate by
        subject raises ``CapabilityUnavailableError``; the engine then fails closed (defers).
        """
        ...

    async def delete(self, record_id: str) -> None: ...

    async def pseudonymize(self, record_id: str) -> None:
        """Replace the record's person identifiers; the record itself stays."""
        ...

    async def export(self, record_id: str) -> Mapping[str, Any]:
        """Redacted content for export. Never a prompt/response body."""
        ...


@runtime_checkable
class PseudonymMappingStore(Protocol):
    """The separate store holding pseudonym -> person mappings (destroyed to erase a person)."""

    async def exists(self, subject_id: str) -> bool: ...

    async def destroy(self, subject_id: str) -> None: ...


@runtime_checkable
class HoldRegistry(Protocol):
    async def place(self, hold: LegalHold) -> None: ...

    async def release(self, hold_id: str) -> bool: ...

    async def active(self) -> list[LegalHold]: ...


class QueuedRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    request: LifecycleRequest
    ctx: AuditContext
    blocked_by: Rule | None
    reason: str
    queued_at: datetime
    not_before: datetime | None = None


@runtime_checkable
class RequestQueue(Protocol):
    async def enqueue(self, item: QueuedRequest) -> bool:
        """Store ``item``; ``False`` (and no change) if an equal request is already queued."""
        ...

    async def pending(self) -> list[QueuedRequest]: ...

    async def remove(self, request_id: str) -> None: ...


class TargetRegistry:
    """Kind + container -> target. The audit container can never be registered."""

    def __init__(self) -> None:
        self._targets: dict[tuple[str, str], LifecycleTarget] = {}

    def register(self, target: LifecycleTarget) -> None:
        if is_audit_container(target.container):
            raise InvalidSchemaError(
                "the audit container cannot be a lifecycle target", reason="audit_immutable"
            )
        self._targets[(target.target_kind, target.container)] = target

    def get(self, target_kind: str, container: str) -> LifecycleTarget | None:
        return self._targets.get((target_kind, container))

    def targets(self) -> list[LifecycleTarget]:
        return list(self._targets.values())
