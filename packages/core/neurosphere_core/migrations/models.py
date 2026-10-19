"""Migration descriptors and the ledger document (PRP-13 item 4).

``MigrationStep`` is a pure descriptor: ``up``/``down`` are functions over plain dicts and never
touch a store. ``MigrationLedger`` is the persisted record of what ran, plus an optional lease
used to serialise runners. Both forbid unknown fields.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

__all__ = [
    "AppliedStep",
    "Lease",
    "MigrationLedger",
    "MigrationStep",
    "MigrationTarget",
    "ledger_id",
]

DocTransform = Callable[[dict[str, Any]], dict[str, Any]]


class MigrationTarget(StrEnum):
    """What a step migrates."""

    COSMOS_DOCUMENTS = "cosmos_documents"
    ANALYTICS_SCHEMA = "analytics_schema"


class MigrationStep(BaseModel):
    """One ordered, reversible schema change for a (target, name) scope."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(min_length=1)
    version: int = Field(ge=1, description="Ordered per (target, name); contiguous from 1.")
    target: MigrationTarget
    name: str = Field(min_length=1, description="Cosmos container or analytics schema name.")
    description: str
    release: str = Field(description="Product SemVer the step ships in.")
    deprecates: list[str] = Field(default_factory=list)
    removes: list[str] = Field(default_factory=list)
    up: DocTransform
    down: DocTransform | None = None


class AppliedStep(BaseModel):
    """Ledger entry for one applied step."""

    model_config = ConfigDict(extra="forbid")

    step_id: str
    version: int
    applied_at: datetime


class Lease(BaseModel):
    """Runner lease; a live lease held by another owner blocks every other runner."""

    model_config = ConfigDict(extra="forbid")

    owner: str
    expires_at: datetime


class MigrationLedger(BaseModel):
    """Ledger document, one per (target, name). ``etag`` is the store's concurrency token."""

    model_config = ConfigDict(extra="forbid")

    id: str
    doc_type: str = "migration_ledger"
    target: MigrationTarget
    name: str
    current_version: int = 0
    applied: list[AppliedStep] = Field(default_factory=list)
    lease: Lease | None = None
    etag: str | None = None


def ledger_id(target: MigrationTarget, name: str) -> str:
    """Deterministic ledger document id for a scope."""
    return f"migration-ledger::{target.value}::{name}"
