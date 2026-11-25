"""Models for sensitive-information detection and typed redaction (PRP-101).

Pure: no I/O, no settings, no logging. Runtime imports are stdlib and pydantic only; the
category strings mirror PRP-99's ``DetectedCategory`` and PRP-70's ``sensitivity_category``
without importing ``neurosphere_contracts`` (tests pin the two vocabularies together).

Nothing here ever holds matched text: a ``Match`` is offsets plus a category, a ``Finding`` is
counts plus placeholder offsets in the redacted text, and a ``RedactionFailed`` is a reason
code only. Error messages raised here name fields and categories, never input text.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Annotated, Final, Literal, cast, get_args

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_serializer,
    field_validator,
    model_validator,
)

#: PRP-99 ``DetectedCategory``. The first eight are credential categories.
Category = Literal[
    "private_key",
    "jwt",
    "bearer_token",
    "cloud_access_key",
    "vendor_api_key",
    "connection_string",
    "url_with_credentials",
    "password_assignment",
    "payment_card",
    "iban",
    "us_ssn",
    "email_address",
    "phone_number",
    "ip_address",
    "mac_address",
    "guid",
    "customer_dictionary_term",
    "customer_identifier_pattern",
    "other",
]

ALL_CATEGORIES: Final[frozenset[str]] = frozenset(get_args(Category))

#: PRP-99 ``CredentialCategory``: always replaced, never kept, not configurable.
CREDENTIAL_CATEGORIES: Final[frozenset[str]] = frozenset(
    {
        "private_key",
        "jwt",
        "bearer_token",
        "cloud_access_key",
        "vendor_api_key",
        "connection_string",
        "url_with_credentials",
        "password_assignment",
    }
)

Confidence = Literal["high", "medium", "low"]
Action = Literal["replaced", "kept"]

#: PRP-99 ``ContentPartKind``.
PartKind = Literal["prompt", "response", "tool_input", "tool_output", "system_instructions"]

#: PRP-70 ``sensitivity_category``.
SensitivityCategory = Literal[
    "pii",
    "phi",
    "cui",
    "pci",
    "financial",
    "biometric",
    "credentials",
    "export_controlled",
    "legal_privileged",
    "other",
]

#: Detected category -> PRP-70 sensitivity category. ``None`` means no default: ``guid`` is not
#: sensitive by itself, and customer terms and patterns carry their configured value on the
#: ``Match`` (``Match.sensitivity_category`` overrides this mapping).
SENSITIVITY_CATEGORY_FOR: Final[Mapping[str, str | None]] = MappingProxyType(
    {
        **dict.fromkeys(sorted(CREDENTIAL_CATEGORIES), "credentials"),
        "payment_card": "pci",
        "iban": "financial",
        "us_ssn": "pii",
        "email_address": "pii",
        "phone_number": "pii",
        "ip_address": "pii",
        "mac_address": "pii",
        "guid": None,
        "customer_dictionary_term": None,
        "customer_identifier_pattern": None,
        "other": "other",
    }
)

RedactionMode = Literal["redact", "keep"]

ReasonCode = Literal["detector_error", "budget_exhausted", "pattern_unsafe", "input_too_large"]

#: Coverage statement the runbook and any UI must use; nothing broader is claimed.
COVERAGE_LABEL: Final = "structured identifiers only"

_PLACEHOLDER_PREFIX: Final = "[[ns-redacted:"
_PLACEHOLDER_SUFFIX: Final = "]]"

#: PRP-99 placeholder grammar ``[[ns-redacted:<detected_category>]]``.
PLACEHOLDER_RE: Final[re.Pattern[str]] = re.compile(
    r"\[\[ns-redacted:(?P<category>[a-z][a-z0-9_]*)\]\]"
)


def placeholder(category: Category) -> str:
    """Typed placeholder for ``category``; no hash, length or partial value (Clarification 4)."""
    if category not in ALL_CATEGORIES:
        raise ValueError("unknown detected category")
    return f"{_PLACEHOLDER_PREFIX}{category}{_PLACEHOLDER_SUFFIX}"


class _Frozen(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class RedactionConfig(_Frozen):
    """Per-category redaction mode (mirrors PRP-99 ``redaction_mode`` / ``kept_categories``).

    Credential categories cannot be set to ``keep``; ``mode_for`` returns ``redact`` for them
    whatever the configuration. ``payment_card`` defaults to ``redact`` but is configurable.
    """

    default_mode: RedactionMode = "redact"
    modes: Mapping[Category, RedactionMode] = Field(default_factory=lambda: MappingProxyType({}))

    @field_validator("modes", mode="after")
    @classmethod
    def _read_only(
        cls, value: Mapping[Category, RedactionMode]
    ) -> Mapping[Category, RedactionMode]:
        return MappingProxyType(dict(value))

    @field_serializer("modes")
    def _plain_dict(self, value: Mapping[Category, RedactionMode]) -> dict[str, str]:
        return {str(k): str(v) for k, v in value.items()}

    @model_validator(mode="after")
    def _credentials_never_kept(self) -> RedactionConfig:
        kept = sorted(
            c for c, m in self.modes.items() if m == "keep" and c in CREDENTIAL_CATEGORIES
        )
        if kept:
            raise ValueError(f"credential categories are always redacted: {', '.join(kept)}")
        return self

    def mode_for(self, category: str) -> RedactionMode:
        if category in CREDENTIAL_CATEGORIES:
            return "redact"
        mode = cast("Mapping[str, RedactionMode]", self.modes).get(category)
        return mode if mode is not None else self.default_mode


class RedactionBudget(_Frozen):
    """Size and time bound for one content part; exhaustion fails the part closed."""

    max_input_chars: int = Field(default=1_000_000, gt=0)
    max_seconds: float = Field(default=2.0, gt=0)
    chunk_chars: int = Field(default=8192, gt=0)
    chunk_overlap: int = Field(default=512, gt=0)

    @model_validator(mode="after")
    def _overlap_below_chunk(self) -> RedactionBudget:
        if self.chunk_overlap >= self.chunk_chars:
            raise ValueError("chunk_overlap must be < chunk_chars")
        return self


@dataclass(frozen=True, slots=True)
class Match:
    """One detector hit: offsets into the scanned text and a category. Never the text."""

    start: int
    end: int
    category: Category
    confidence: Confidence
    detector_id: str
    #: Overrides ``SENSITIVITY_CATEGORY_FOR`` (customer detectors supply their configured value).
    sensitivity_category: str | None = None

    def __post_init__(self) -> None:
        if self.start < 0 or self.end <= self.start:
            raise ValueError("match offsets must satisfy 0 <= start < end")
        if self.category not in ALL_CATEGORIES:
            raise ValueError("match category is not a known detected category")
        if self.confidence not in get_args(Confidence):
            raise ValueError("match confidence must be high, medium or low")


_DetectorId = Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9._-]{0,63}$")]
_Version = Annotated[str, Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$")]
_Offset = Annotated[int, Field(ge=0)]


class Finding(_Frozen):
    """PRP-99 ``DetectionFinding`` fields plus the PRP-70 ``sensitivity_category``.

    ``offsets`` are placeholder spans ``(start, end)`` in the REDACTED text (PRP-99 ``spans``,
    at most 64). A finding never holds matched text; a credential category is always replaced.
    """

    category: Category
    part: PartKind
    detector_id: _DetectorId
    detector_version: _Version
    count: int = Field(ge=1, le=100_000)
    action: Action
    confidence: Confidence
    offsets: tuple[tuple[_Offset, _Offset], ...] = Field(default=(), max_length=64)
    sensitivity_category: SensitivityCategory | None

    @model_validator(mode="after")
    def _consistent(self) -> Finding:
        if self.category in CREDENTIAL_CATEGORIES and self.action != "replaced":
            raise ValueError("a credential category is always replaced")
        if any(end < start for start, end in self.offsets):
            raise ValueError("offsets must satisfy start <= end")
        return self


class Redacted(_Frozen):
    """Successful redaction: normalized, redacted text plus findings."""

    text: str
    findings: tuple[Finding, ...] = ()
    #: Detector-set version; PRP-99 ``RedactedContent.detector_set_version`` grammar.
    set_version: _DetectorId


class RedactionFailed(_Frozen):
    """Fail-closed result: a reason code only; no text and no partial output."""

    reason: ReasonCode


RedactionResult = Redacted | RedactionFailed
