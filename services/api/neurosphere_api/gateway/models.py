"""Request and response models of the gateway registry API (PRP-33 item 6)."""

from __future__ import annotations

from typing import Annotated

from neurosphere_core.gateway import GatewayRegistration
from neurosphere_core.gateway.models import ARM_ID_PATTERN
from pydantic import BaseModel, ConfigDict, Field, StringConstraints

__all__ = ["GatewayDetail", "GatewayList", "RegisterGatewayBody"]


class RegisterGatewayBody(BaseModel):
    """Register by ARM resource id. ``customer_id``/``domain_id``/identity are never in the body."""

    model_config = ConfigDict(extra="forbid")

    arm_resource_id: Annotated[str, StringConstraints(pattern=f"(?i){ARM_ID_PATTERN}")]
    workspace_id: Annotated[
        str | None,
        StringConstraints(
            pattern=r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
        ),
    ] = None


class GatewayDetail(GatewayRegistration):
    """Registration plus the inventory summary (full snapshot: ``.../inventory``)."""

    inventory_counts: dict[str, int] | None = Field(default=None)
    inventory_taken_at: str | None = None


class GatewayList(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[GatewayRegistration]
    next_cursor: str | None = None
