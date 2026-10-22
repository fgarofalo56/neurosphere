"""Response model for ``GET /api/v1/workspaces/{role}`` (PRP-28 item 1)."""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

__all__ = ["WorkspaceBody"]


class WorkspaceBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workspace: Literal["viewer", "analyst", "steward", "admin", "auditor"]
    items: list[dict[str, Any]]
