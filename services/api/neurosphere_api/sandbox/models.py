"""Response models for the sandbox API (PRP-24 item 2). All bodies are marked synthetic."""

from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

__all__ = ["EntityPage", "ResetResult", "SandboxKind", "SandboxSummary"]


class SandboxKind(StrEnum):
    """Closed set of entity kinds the PRP-03 generator writes to ``sandbox-entities``."""

    DOMAIN = "domain"
    OWNER = "owner"
    PERSON = "person"
    MODEL_DEPLOYMENT = "model_deployment"
    GROUNDING_SOURCE = "grounding_source"
    TOOL = "tool"
    AGENT = "agent"
    AGENT_VERSION = "agent_version"


class SandboxSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    environment: Literal["sandbox"] = "sandbox"
    synthetic: Literal[True] = True
    customer_id: Literal["synthco"] = "synthco"
    database: str
    counts: dict[str, int]
    relations: int
    total: int


class EntityPage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    environment: Literal["sandbox"] = "sandbox"
    synthetic: Literal[True] = True
    kind: SandboxKind
    items: list[dict[str, Any]]
    limit: int = Field(ge=1)
    offset: int = Field(ge=0)
    next_offset: int | None


class ResetResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    environment: Literal["sandbox"] = "sandbox"
    synthetic: Literal[True] = True
    deleted: dict[str, int]
