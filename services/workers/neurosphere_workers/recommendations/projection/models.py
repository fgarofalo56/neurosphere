"""Typed inputs for cost projections (PRP-15 item 3). All frozen, ``extra="forbid"``."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from decimal import Decimal
from typing import Annotated, Final, Literal, Self

from neurosphere_core.ledger.models import TokenCounts
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Cloud = Literal["commercial", "government"]

CANONICAL_ID: Final = re.compile(
    r"^(commercial|government):[a-z0-9._-]+:[a-z0-9._-]+:[a-z0-9._-]+:[a-z0-9._/=-]+$"
)
OPAQUE_ID: Final = re.compile(r"^[a-z0-9][a-z0-9._:/=-]{0,255}$")
SLUG: Final = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
VERSION: Final = re.compile(r"^[A-Za-z0-9._+-]{1,64}$")
CUSTOMER: Final = re.compile(r"^[a-z0-9._-]{1,128}$")


class _Frozen(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


def _canonical(value: str) -> str:
    if not CANONICAL_ID.match(value) or len(value) > 512:
        raise ValueError("not a canonical id (cloud:customer:source:type:id)")
    return value


class UsageSummary(_Frozen):
    """Token usage of one agent on one model over an evidence window.

    Token fields are ``None`` when unknown. Unknown is never treated as 0: a summary with unknown
    input or output tokens yields no projection.
    """

    agent_id: str
    cloud: Cloud
    customer_id: str
    domain_id: str
    owner_id: str | None = None
    provider: str = Field(min_length=1)
    current_model: str = Field(min_length=1)
    current_model_version: str | None = None
    deployment_id: str | None = None
    tokens: TokenCounts
    window_start: datetime
    window_end: datetime
    evidence_ids: tuple[str, ...] = Field(default=(), max_length=200)
    coverage_method: Literal["full", "sampled", "partial", "unknown"] = "unknown"
    observed_fraction: Annotated[float, Field(ge=0.0, le=1.0, strict=True)] | None = None
    missing_source_ids: tuple[str, ...] = Field(default=(), max_length=100)

    @field_validator("customer_id")
    @classmethod
    def _customer(cls, value: str) -> str:
        if not CUSTOMER.match(value):
            raise ValueError("customer_id shape")
        return value

    @field_validator("agent_id", "domain_id")
    @classmethod
    def _ids(cls, value: str) -> str:
        return _canonical(value)

    @field_validator("owner_id", "deployment_id")
    @classmethod
    def _optional_ids(cls, value: str | None) -> str | None:
        return None if value is None else _canonical(value)

    @field_validator("missing_source_ids")
    @classmethod
    def _missing(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        for item in value:
            _canonical(item)
        if len(set(value)) != len(value):
            raise ValueError("duplicate missing_source_ids")
        return value

    @field_validator("evidence_ids")
    @classmethod
    def _evidence(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        for item in value:
            if not OPAQUE_ID.match(item):
                raise ValueError("evidence id is not an opaque id")
        if len(set(value)) != len(value):
            raise ValueError("duplicate evidence_ids")
        return value

    @field_validator("window_start", "window_end")
    @classmethod
    def _aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("timestamp has no timezone")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        if not self.window_start < self.window_end:
            raise ValueError("window_start must precede window_end")
        prefix = f"{self.cloud}:{self.customer_id}:"
        ids = [self.agent_id, self.domain_id, self.owner_id, self.deployment_id]
        ids += list(self.missing_source_ids)
        for value in ids:
            if value is not None and not value.startswith(prefix):
                raise ValueError(f"{value!r} is outside {self.cloud}:{self.customer_id}")
        return self


class CandidatePair(_Frozen):
    """One configured current -> candidate model pairing. Configuration, not a selection."""

    pair_id: str
    provider: str = Field(min_length=1)
    current_model: str = Field(min_length=1)
    current_model_version: str | None = None
    candidate_provider: str | None = None  # None = same provider as ``provider``
    candidate_model: str = Field(min_length=1)
    candidate_model_version: str | None = None

    @field_validator("pair_id")
    @classmethod
    def _slug(cls, value: str) -> str:
        if not SLUG.match(value):
            raise ValueError("pair_id must match ^[a-z0-9][a-z0-9._-]{0,63}$")
        return value

    def matches(self, usage: UsageSummary) -> bool:
        if usage.provider != self.provider or usage.current_model != self.current_model:
            return False
        return (
            self.current_model_version is None
            or self.current_model_version == usage.current_model_version
        )


class CandidatePairConfig(_Frozen):
    """Versioned candidate-pair config. ``volume_band`` is the relative token-volume uncertainty
    (for example 0.20 = plus or minus 20%) used for the projection range."""

    config_id: str
    version: str
    volume_band: Decimal = Field(default=Decimal("0.20"), gt=0, lt=1)
    pairs: tuple[CandidatePair, ...]

    @field_validator("config_id")
    @classmethod
    def _slug(cls, value: str) -> str:
        if not SLUG.match(value):
            raise ValueError("config_id must match ^[a-z0-9][a-z0-9._-]{0,63}$")
        return value

    @field_validator("version")
    @classmethod
    def _version(cls, value: str) -> str:
        if not VERSION.match(value):
            raise ValueError("version shape")
        return value

    @model_validator(mode="after")
    def _unique(self) -> Self:
        ids = [p.pair_id for p in self.pairs]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate pair_id")
        return self

    def pairs_for(self, usage: UsageSummary) -> list[CandidatePair]:
        return [p for p in self.pairs if p.matches(usage)]
