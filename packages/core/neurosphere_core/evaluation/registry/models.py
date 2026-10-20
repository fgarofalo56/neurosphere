"""Versioned evaluation registry models (PRP-16 item 1).

Datasets, rubrics and judge configs are immutable values identified by ``(id, version)``. An edit
is a new version, never a mutation (see ``store``). Id and version patterns mirror the
``EvaluationResult`` contract (``opaque_id``, ``version``, ``canonical_id``).
"""

from __future__ import annotations

import hashlib
import json
from typing import Annotated, Any, Final, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

__all__ = [
    "CLASSIFICATIONS",
    "Classification",
    "Cloud",
    "Criterion",
    "DatasetItem",
    "DatasetVersion",
    "Dimension",
    "JudgeConfig",
    "JudgeKind",
    "RubricVersion",
    "compute_content_hash",
    "normalize_classification",
]

OPAQUE_ID_PATTERN: Final = r"^[a-z0-9][a-z0-9._:/=-]{0,255}$"
VERSION_PATTERN: Final = r"^[A-Za-z0-9._+-]{1,64}$"
CANONICAL_ID_PATTERN: Final = (
    r"^(commercial|government):[a-z0-9._-]+:[a-z0-9._-]+:[a-z0-9._-]+:[a-z0-9._/=-]+$"
)
DECIMAL_PATTERN: Final = r"^(0|[1-9][0-9]*)(\.[0-9]{1,12})?$"
TIMESTAMP_PATTERN: Final = (
    r"^[0-9]{4}-(0[1-9]|1[0-2])-(0[1-9]|[12][0-9]|3[01])T([01][0-9]|2[0-3]):[0-5][0-9]:[0-5][0-9]"
    r"(\.[0-9]{1,9})?Z$"
)

OpaqueId = Annotated[str, Field(pattern=OPAQUE_ID_PATTERN)]
Version = Annotated[str, Field(pattern=VERSION_PATTERN)]
CanonicalId = Annotated[str, Field(pattern=CANONICAL_ID_PATTERN, max_length=512)]
Decimal = Annotated[str, Field(pattern=DECIMAL_PATTERN)]
Timestamp = Annotated[str, Field(pattern=TIMESTAMP_PATTERN)]

Dimension = Literal["task_success", "groundedness", "safety", "tool_correctness"]
Cloud = Literal["commercial", "government"]
Classification = Literal["public", "internal", "cui", "restricted"]
# ``human`` is a valid result judge_kind in the contract but never a registered config kind.
JudgeKind = Literal["llm_judge", "programmatic", "hybrid"]
DatasetKind = Literal["offline_benchmark", "sampling_frame"]
DataState = Literal["synthetic", "redacted", "approved"]

CLASSIFICATIONS: Final[tuple[Classification, ...]] = ("public", "internal", "cui", "restricted")


def normalize_classification(value: str | None) -> Classification:
    """Map a telemetry classification to the vocabulary; null/unknown fails closed (restricted)."""
    for known in CLASSIFICATIONS:
        if value == known:
            return known
    return "restricted"


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


class DatasetItem(BaseModel):
    """One benchmark item. ``payload`` is the redacted, JSON-safe content a judge may see."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    item_id: OpaqueId
    dimension: Dimension
    classification: Classification
    payload: dict[str, Any]

    @model_validator(mode="after")
    def _payload_is_json_safe(self) -> Self:
        try:
            _canonical_json(self.payload)
        except (TypeError, ValueError) as exc:
            raise ValueError("payload must be JSON-serialisable") from exc
        return self


def compute_content_hash(
    kind: str, dimensions: tuple[Dimension, ...], items: tuple[DatasetItem, ...]
) -> str:
    """sha256 over canonical JSON of kind, dimensions and items (not id, version or timestamp)."""
    body = {
        "kind": kind,
        "dimensions": list(dimensions),
        "items": [i.model_dump(mode="json") for i in items],
    }
    return hashlib.sha256(_canonical_json(body).encode("utf-8")).hexdigest()


class DatasetVersion(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    dataset_id: OpaqueId
    version: Version
    kind: DatasetKind
    dimensions: tuple[Dimension, ...] = Field(min_length=1)
    items: tuple[DatasetItem, ...] = Field(min_length=1)
    content_hash: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    data_state: DataState
    created_at: Timestamp

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        if len({i.item_id for i in self.items}) != len(self.items):
            raise ValueError("duplicate item_id in dataset")
        unknown = {i.dimension for i in self.items} - set(self.dimensions)
        if unknown:
            raise ValueError(f"items use dimensions not declared: {sorted(unknown)}")
        expected = compute_content_hash(self.kind, self.dimensions, self.items)
        if self.content_hash != expected:
            raise ValueError("content_hash does not match the dataset content")
        return self

    @classmethod
    def build(
        cls,
        *,
        dataset_id: str,
        version: str,
        kind: DatasetKind,
        dimensions: tuple[Dimension, ...],
        items: tuple[DatasetItem, ...],
        data_state: DataState,
        created_at: str,
    ) -> Self:
        """Construct with the content hash computed."""
        return cls(
            dataset_id=dataset_id,
            version=version,
            kind=kind,
            dimensions=dimensions,
            items=items,
            content_hash=compute_content_hash(kind, dimensions, items),
            data_state=data_state,
            created_at=created_at,
        )


class Criterion(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    criterion_id: OpaqueId
    dimension: Dimension
    description: Annotated[str, Field(min_length=1, max_length=1000)]


class RubricVersion(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    rubric_id: OpaqueId
    version: Version
    dimensions: tuple[Dimension, ...] = Field(min_length=1)
    criteria: tuple[Criterion, ...] = Field(min_length=1)
    scale_min: float
    scale_max: float

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        if self.scale_min >= self.scale_max:
            raise ValueError("scale_min must be below scale_max")
        unknown = {c.dimension for c in self.criteria} - set(self.dimensions)
        if unknown:
            raise ValueError(f"criteria use dimensions not declared: {sorted(unknown)}")
        return self


class JudgeConfig(BaseModel):
    """A judge's identity, boundary, approvals and price. ``human`` is not a config kind."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    judge_config_id: OpaqueId
    version: Version
    judge_kind: JudgeKind
    cloud: Cloud
    judge_model_id: CanonicalId | None = None
    judge_model_version: Version | None = None
    judge_prompt_version: Version | None = None
    program_version: Version | None = None
    capability_row_id: str | None = None
    approved_classifications: tuple[Classification, ...]
    max_output_tokens: Annotated[int, Field(gt=0)]
    input_price_per_1k_tokens: Decimal | None = None
    output_price_per_1k_tokens: Decimal | None = None
    price_version: Version | None = None

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        if len(set(self.approved_classifications)) != len(self.approved_classifications):
            raise ValueError("duplicate approved_classifications")
        if self.judge_kind == "programmatic":
            if self.program_version is None:
                raise ValueError("programmatic judge requires program_version")
            if any(
                v is not None
                for v in (self.judge_model_id, self.judge_model_version, self.judge_prompt_version)
            ):
                raise ValueError("programmatic judge must not carry model fields")
            return self
        missing = [
            n
            for n in (
                "judge_model_id",
                "judge_model_version",
                "judge_prompt_version",
                "capability_row_id",
                "input_price_per_1k_tokens",
                "output_price_per_1k_tokens",
                "price_version",
            )
            if getattr(self, n) is None
        ]
        if missing:
            raise ValueError(f"{self.judge_kind} judge requires {', '.join(missing)}")
        if self.judge_kind == "llm_judge" and self.program_version is not None:
            raise ValueError("llm_judge must not carry program_version")
        if self.judge_model_id is None or not self.judge_model_id.startswith(f"{self.cloud}:"):
            raise ValueError("judge_model_id cloud segment must equal config cloud")
        return self
