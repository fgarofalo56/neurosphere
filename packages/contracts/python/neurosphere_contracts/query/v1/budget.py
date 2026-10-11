# GENERATED - do not edit.
# Source of truth: packages/contracts/schemas/ (JSON Schema 2020-12).
# Regenerate: python packages/contracts/scripts/generate.py
# Drift check: python packages/contracts/scripts/generate.py --check (ADR-0004).
# pyright: reportAssignmentType=false, reportInvalidTypeForm=false

from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StrictInt


class Budget(BaseModel):
    """
    Shared bounded-execution budget for every query, traversal, search, export and viewport expansion (PRP-01 clarification 15; NS-05, NS-06). timeout_ms, limit and max_depth are mandatory. The maxima here are contract ceilings; the server may clamp to lower policy values and reports the effective values and any truncation in Page. Not a standalone document, so it carries no schema_version.
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    timeout_ms: Annotated[StrictInt, Field(ge=1, le=30000)]
    """
    Wall-clock budget in integer milliseconds.
    """
    limit: Annotated[StrictInt, Field(ge=1, le=1000)]
    """
    Maximum rows (or root items) per page.
    """
    max_depth: Annotated[StrictInt, Field(ge=0, le=5)]
    """
    Maximum traversal depth. 0 for non-graph queries.
    """
    max_nodes: Annotated[StrictInt | None, Field(ge=1, le=5000)] = None
    """
    Maximum graph nodes returned (viewport budget). Absent means the server policy default, never unbounded.
    """
    max_edges: Annotated[StrictInt | None, Field(ge=1, le=20000)] = None
    """
    Maximum graph edges returned (viewport budget). Absent means the server policy default, never unbounded.
    """
