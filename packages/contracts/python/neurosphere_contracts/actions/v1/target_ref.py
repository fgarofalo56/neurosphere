# GENERATED - do not edit.
# Source of truth: packages/contracts/schemas/ (JSON Schema 2020-12).
# Regenerate: python packages/contracts/scripts/generate.py
# Drift check: python packages/contracts/scripts/generate.py --check (ADR-0004).
# pyright: reportAssignmentType=false, reportInvalidTypeForm=false

from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StrictStr


class TargetRef(BaseModel):
    """
    Reference to the resource an action changes or an audit record concerns. `canonical_id` uses the catalog grammar `cloud:customer:source:type:id` (Clarification 7); the pattern here mirrors it and the catalog/v1 grammar is authoritative. Python validator `validate_target_ref_matches_catalog_grammar` in tests/contracts/test_canonical_ids.py checks this pattern against the catalog ID corpus so the two cannot drift. The version being acted on is carried beside this object (ActionIntent.target_version), not inside it, so it is hashed as its own field.
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    canonical_id: Annotated[
        StrictStr,
        Field(
            max_length=512,
            pattern="^(commercial|government):[a-z0-9._-]+:[a-z0-9._-]+:[a-z0-9._-]+:[a-z0-9._/=-]+$",
        ),
    ]
    """
    Cloud/customer/source qualified canonical ID of the target.
    """
    entity_type: Annotated[StrictStr, Field(pattern="^[a-z][a-z0-9_]{0,63}$")]
    """
    Catalog entity type of the target, lowercase snake_case (for example `model_deployment`, `agent_version`).
    """
