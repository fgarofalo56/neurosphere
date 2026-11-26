"""Port ``InteractionFindingReader``: detection-finding counts, metadata only (PRP-105 item 2).

Unbound here. PRP-104 item 8 binds a reader through the binding functions of PRP-105 items 5
and 6 (``interaction_finding_reader``); until then ``content_rule`` is unavailable. A reader
returns counts of PRP-99 ``DetectionFinding`` categories per subject and the ids of the
interaction records they came from. It never returns, and the evaluator never asks for, an
interaction body, a matched value or an offset.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Annotated, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr

from neurosphere_core.scope import IdentityScope

__all__ = ["FindingCountPage", "InteractionFindingCount", "InteractionFindingReader"]

_REF = r"^[A-Za-z0-9._:/=-]{1,512}$"


class InteractionFindingCount(BaseModel):
    """Findings of one detected category for one subject in a window: counts and ids only."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    subject_id: Annotated[StrictStr, Field(max_length=512, pattern=_REF)]
    """Canonical id of the agent (or other subject) the interactions belong to."""
    subject_type: Annotated[StrictStr, Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")]
    domain_id: StrictStr | None
    category: StrictStr
    """A PRP-99 ``DetectedCategory`` value (open-ended)."""
    count: Annotated[StrictInt, Field(ge=0)]
    """Matches of the category summed over the window (``DetectionFinding.count``)."""
    interaction_ids: Annotated[
        tuple[Annotated[StrictStr, Field(pattern=_REF)], ...], Field(max_length=50)
    ] = ()
    """Some interaction record ids carrying the findings (references, never content)."""


class FindingCountPage(BaseModel):
    """A bounded answer; ``truncated`` when more subjects matched than ``limit``."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    counts: tuple[InteractionFindingCount, ...] = ()
    truncated: bool = False


@runtime_checkable
class InteractionFindingReader(Protocol):
    """Reads detection-finding counts from interaction metadata, within the caller's scope."""

    async def count_findings(
        self,
        scope: IdentityScope,
        *,
        domain_ids: Sequence[str],
        categories: Sequence[str],
        parts: Sequence[str],
        start: datetime,
        end: datetime,
        limit: int,
    ) -> FindingCountPage:
        """Counts per (subject, category) of interactions in ``[start, end)`` whose findings
        have one of ``categories`` in one of ``parts`` (empty means every part), at most
        ``limit`` subjects. Domains outside ``scope`` are dropped, never widened."""
        ...
