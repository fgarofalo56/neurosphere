# GENERATED - do not edit.
# Source of truth: packages/contracts/schemas/ (JSON Schema 2020-12).
# Regenerate: python packages/contracts/scripts/generate.py
# Drift check: python packages/contracts/scripts/generate.py --check (ADR-0004).
# pyright: reportAssignmentType=false, reportInvalidTypeForm=false

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, RootModel, StrictStr

from ...catalog.v1 import common
from . import enforcement_binding


class Model(BaseModel):
    """
    Model about to be called.
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    model_name: Annotated[StrictStr | None, Field(max_length=128, min_length=1)]
    model_version: Annotated[StrictStr | None, Field(max_length=128, min_length=1)]
    deployment_id: common.CanonicalId | None
    """
    Deployment canonical id.
    """


class RequestRef(RootModel[StrictStr]):
    root: Annotated[StrictStr, Field(pattern="^[A-Za-z0-9._-]{1,128}$")] = None
    """
    Caller's opaque request id for correlation.
    """


class PolicyDecisionRequest(BaseModel):
    """
    Ask whether an operation is allowed (PRP-99). Carries no scope field: cloud, customer and domain come from the server-derived identity, so domain_id and customer_id are rejected as unknown keys, and no prompt or content field exists. At least one subject must be named (Python validator check_decision_request_subject in tests/contracts/validators.py). Nullable fields are optional and default to null.
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    schema_version: common.SchemaVersion
    decision_point: enforcement_binding.EnforcementPoint
    operation: Literal["model_call", "tool_invoke", "mcp_call", "data_access", "register"]
    agent_id: common.CanonicalId | None = None
    """
    Agent canonical id.
    """
    agent_version_id: common.CanonicalId | None = None
    """
    Agent version canonical id.
    """
    tool_id: common.CanonicalId | None = None
    """
    Tool canonical id.
    """
    mcp_server_id: common.CanonicalId | None = None
    """
    MCP server canonical id.
    """
    model: Model | None = None
    """
    Model about to be called.
    """
    data_asset_ids: Annotated[
        list[common.CanonicalId] | None, Field(max_length=20, validate_default=True)
    ] = []
    """
    Data assets touched.
    """
    access: Literal["read", "write"] | None = None
    """
    Kind of data access.
    """
    environment: common.Environment | None = None
    """
    Deployment environment.
    """
    request_ref: RequestRef | None = None
    """
    Caller's opaque request id for correlation.
    """
