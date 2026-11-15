"""Response models of the PRP-40 audit routes (search page and SIEM status)."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from neurosphere_contracts.audit.v1.audit_record import AuditRecord
from pydantic import BaseModel, ConfigDict, Field

__all__ = ["AuditSearchHit", "AuditSearchPage", "AuditSiemStatus"]


class AuditSearchHit(BaseModel):
    """One matching record and the domain whose chain holds it."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    domain_id: str
    record: AuditRecord


class AuditSearchPage(BaseModel):
    """Newest first; ``next_cursor`` is opaque and only valid with the same domains."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    items: Annotated[tuple[AuditSearchHit, ...], Field(max_length=500)]
    next_cursor: str | None = None
    domains: tuple[str, ...]


class AuditSiemStatus(BaseModel):
    """Configured SIEM sink and its runtime delivery health. Reason codes only: never a host,
    hub name, key or exception text."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    sink: Literal["none", "stdout", "file", "eventhubs", "unknown"]
    state: Literal["ok", "disabled", "failed", "not_built"]
    reason: str | None = None
    last_success_at: datetime | None = None
    last_failure_at: datetime | None = None
    consecutive_failures: int = 0
    total_failures: int = 0
    total_sent: int = 0
    last_failure_reason: str | None = None
