"""Response models for ``GET /api/v1/me/domains`` (PRP-28 item 1)."""

from typing import Literal

from pydantic import BaseModel, ConfigDict

__all__ = ["DomainView", "MeDomains"]


class DomainView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    domain_id: str
    display_name: str
    display_name_source: Literal["catalog", "derived"]
    cloud: Literal["commercial", "government"]
    permissions: list[str]


class MeDomains(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[DomainView]
