"""Response bodies of the interaction explorer (PRP-104 item 2).

Items are the PRP-99 contract ``InteractionRecord`` itself: metadata, findings summary and
redaction state. The contract has no content-bearing property, so nothing here can carry captured
content.
"""

from __future__ import annotations

from typing import Annotated

from neurosphere_contracts.interactions.v1.interaction_record import InteractionRecord
from neurosphere_core.interactions import MAX_QUERY_PAGE_SIZE
from pydantic import BaseModel, ConfigDict, Field

__all__ = ["InteractionPage"]


class InteractionPage(BaseModel):
    """One page of interaction metadata, newest ``captured_at`` first."""

    model_config = ConfigDict(extra="forbid")

    items: Annotated[list[InteractionRecord], Field(max_length=MAX_QUERY_PAGE_SIZE)]
    #: Opaque token for the next page; ``None`` on the last page.
    continuation: str | None = None
