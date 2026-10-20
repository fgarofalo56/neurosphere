"""Human-label ingestion (PRP-16 item 3, Clarification 11).

PRP-17's HITL review queue hands labels over as ``HumanLabelRecord`` objects (any object with a
``labels()`` method satisfies ``LabelSource``). This module only defines label use: validation,
conflict rejection and a consensus rule. There is no labeling tool and no I/O here.

Rules:
- All records of one ingest share one ``label_set_version`` (mixed versions are rejected).
- The same labeler giving two different values for one (item, dimension) is a conflict and is
  rejected (``InvalidSchemaError``, reason ``conflicting_labels``); an identical duplicate is
  collapsed.
- Several labelers are kept. Consensus is the **strict majority value** (the mode, when it is held
  by more labelers than any other value). A tie has no consensus (``None``): the item then counts
  as unlabelled instead of guessing, and the mean is not used because it invents values that no
  labeler gave (0.5 for a binary label).
"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Iterable
from datetime import datetime
from typing import Annotated, Final, Literal, Protocol, runtime_checkable

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from neurosphere_core.errors import InvalidSchemaError

__all__ = [
    "VERSION_PATTERN",
    "Dimension",
    "HumanLabelRecord",
    "LabelSet",
    "LabelSource",
    "ingest_labels",
]

Dimension = Literal[
    "task_success", "groundedness", "safety", "tool_correctness", "user_feedback", "drift"
]

VERSION_PATTERN: Final = r"^[A-Za-z0-9._+-]{1,64}$"
_ID_PATTERN: Final = r"^[A-Za-z0-9][A-Za-z0-9._:/=-]{0,255}$"

Version = Annotated[str, Field(pattern=VERSION_PATTERN)]


class HumanLabelRecord(BaseModel):
    """One human judgement of one item on one dimension (numeric: 0/1, category code or rating)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    item_id: str = Field(pattern=_ID_PATTERN)
    dimension: Dimension
    label_set_version: Version
    value: float = Field(allow_inf_nan=False)
    labeler: str = Field(pattern=_ID_PATTERN, description="Pseudonymous labeler id, never a name.")
    labelled_at: AwareDatetime


@runtime_checkable
class LabelSource(Protocol):
    """The PRP-17 HITL queue adapter."""

    def labels(self) -> Iterable[HumanLabelRecord]: ...


class LabelSet(BaseModel):
    """Validated, conflict-free labels of one ``label_set_version``."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    label_set_version: Version
    records: tuple[HumanLabelRecord, ...]

    def consensus(self, item_id: str, dimension: str) -> float | None:
        """Strict-majority label for the item, or ``None`` (unlabelled or tied)."""
        return self.consensus_map(dimension).get(item_id)

    def consensus_map(self, dimension: str) -> dict[str, float]:
        by_item: dict[str, list[float]] = defaultdict(list)
        for rec in self.records:
            if rec.dimension == dimension:
                by_item[rec.item_id].append(rec.value)
        out: dict[str, float] = {}
        for item_id, values in by_item.items():
            ranked = Counter(values).most_common(2)
            if len(ranked) == 1 or ranked[0][1] > ranked[1][1]:
                out[item_id] = ranked[0][0]
        return out

    def labeler_count(self, item_id: str, dimension: str) -> int:
        return len(
            {r.labeler for r in self.records if r.item_id == item_id and r.dimension == dimension}
        )

    @property
    def latest_labelled_at(self) -> datetime | None:
        return max((r.labelled_at for r in self.records), default=None)


def ingest_labels(records: Iterable[HumanLabelRecord] | LabelSource) -> LabelSet:
    """Validate ``records`` (or a ``LabelSource``) into a ``LabelSet``."""
    items = list(records.labels() if isinstance(records, LabelSource) else records)
    if not items:
        raise InvalidSchemaError("no labels to ingest", reason="empty_label_set")
    versions = {r.label_set_version for r in items}
    if len(versions) != 1:
        raise InvalidSchemaError(
            "labels span several label_set_versions", reason="mixed_label_set_versions"
        )
    seen: dict[tuple[str, str, str], HumanLabelRecord] = {}
    for rec in items:
        key = (rec.item_id, rec.dimension, rec.labeler)
        prior = seen.get(key)
        if prior is None:
            seen[key] = rec
        elif prior.value != rec.value:
            raise InvalidSchemaError(
                "labeler gave conflicting labels for one item and dimension",
                reason="conflicting_labels",
            )
    return LabelSet(label_set_version=versions.pop(), records=tuple(seen.values()))
