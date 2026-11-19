# GENERATED - do not edit.
# Source of truth: packages/contracts/schemas/ (JSON Schema 2020-12).
# Regenerate: python packages/contracts/scripts/generate.py
# Drift check: python packages/contracts/scripts/generate.py --check (ADR-0004).
# pyright: reportAssignmentType=false, reportInvalidTypeForm=false

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictFloat, StrictStr

from . import common


class EntityRevisionChange(BaseModel):
    """
    One differing field. path is an RFC 6901 JSON Pointer into the entity document (one to six lowercase snake_case segments, no array indexes).
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    path: Annotated[StrictStr, Field(pattern="^(/[a-z0-9_]{1,64}){1,6}$")]
    op: Literal["added", "removed", "changed"]
    before: StrictStr | StrictFloat | StrictBool | list[Any] | None = None
    """
    Value in from_version; null when op is added.
    """
    after: StrictStr | StrictFloat | StrictBool | list[Any] | None = None
    """
    Value in to_version; null when op is removed.
    """


class EntityRevisionCapabilityChanges(BaseModel):
    """
    Declared capabilities added to and removed from the entity between the two versions.
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    added: Annotated[list[common.Capability], Field(max_length=64)]
    removed: Annotated[list[common.Capability], Field(max_length=64)]


class EntityRevisionTagChanges(BaseModel):
    """
    Tags added to and removed from the entity between the two versions.
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    added: Annotated[list[common.Tag], Field(max_length=64)]
    removed: Annotated[list[common.Tag], Field(max_length=64)]


class EntityRevisionDiff(BaseModel):
    """
    Computed difference between two retained revisions of one catalog entity (PRP-70; computed on read by PRP-76, never stored). Answers 'what changed between version N and M' including the declared-capability and tag diff of the original 5b story. changes is capped at 200 entries; truncated is true when more differences existed than were returned. before and after hold the compared values at that path (a scalar or a list, null when absent on that side; changed members of nested objects are reported as deeper paths, so a value is never an object) and are the entity's own field values, so the diff inherits the entity's visibility rules. Python validators: check_revision_version_order (from_version < to_version).
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    schema_version: common.SchemaVersion
    entity_id: common.CanonicalId
    entity_type: common.EntityType
    from_version: common.EntityVersion
    to_version: common.EntityVersion
    changes: Annotated[list[EntityRevisionChange], Field(max_length=200)]
    capability_changes: EntityRevisionCapabilityChanges
    tag_changes: EntityRevisionTagChanges
    truncated: StrictBool
    """
    True when the changes list was cut at its cap.
    """
