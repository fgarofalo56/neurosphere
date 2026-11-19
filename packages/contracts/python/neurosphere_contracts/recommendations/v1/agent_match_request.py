# GENERATED - do not edit.
# Source of truth: packages/contracts/schemas/ (JSON Schema 2020-12).
# Regenerate: python packages/contracts/scripts/generate.py
# Drift check: python packages/contracts/scripts/generate.py --check (ADR-0004).
# pyright: reportAssignmentType=false, reportInvalidTypeForm=false

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr

from ...catalog.v1 import common


class AgentMatchRequest(BaseModel):
    """
    Task-to-agent match request (PRP-70 item 3). task_text is tokenized for ranking only: it is never executed, never sent to an LLM for explanation and never stored (feedback keeps only a digest). The request carries no scope field: cloud, customer and domain scope come from the server-derived IdentityScope, so domain_id and customer_id are rejected as unknown keys. Nullable fields are optional and default to null.
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    schema_version: common.SchemaVersion
    task_text: Annotated[
        StrictStr,
        Field(
            max_length=2000,
            min_length=3,
            pattern="^[^\\u0000-\\u0008\\u000b-\\u001f\\u007f]+$",
        ),
    ]
    """
    Natural-language task description, 3 to 2000 characters. Control characters other than tab and newline are rejected. Tokenized only, never executed or stored.
    """
    candidate_types: Annotated[
        list[Literal["agent", "tool"]] | None, Field(max_length=2, min_length=1)
    ] = ["agent"]
    """
    Entity types to rank.
    """
    required_capabilities: Annotated[
        list[common.Capability] | None, Field(max_length=16, validate_default=True)
    ] = []
    preferred_tags: Annotated[
        list[common.Tag] | None, Field(max_length=16, validate_default=True)
    ] = []
    context_entity_ids: Annotated[
        list[common.CanonicalId] | None, Field(max_length=20, validate_default=True)
    ] = []
    """
    Canonical IDs of entities the task relates to; used as graph-proximity anchors.
    """
    environment: common.Environment | None = None
    """
    Restrict candidates to one environment; null means any.
    """
    limit: Annotated[StrictInt | None, Field(ge=1, le=50)] = 10
    max_graph_depth: Annotated[StrictInt | None, Field(ge=0, le=3)] = 2
