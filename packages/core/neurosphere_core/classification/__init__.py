"""Sensitive-information detectors and typed redaction (PRP-101).

Pure; structured identifiers only.
"""

from __future__ import annotations

from neurosphere_core.classification.models import (
    ALL_CATEGORIES,
    COVERAGE_LABEL,
    CREDENTIAL_CATEGORIES,
    PLACEHOLDER_RE,
    SENSITIVITY_CATEGORY_FOR,
    Action,
    Category,
    Confidence,
    Finding,
    Match,
    PartKind,
    ReasonCode,
    Redacted,
    RedactionBudget,
    RedactionConfig,
    RedactionFailed,
    RedactionMode,
    RedactionResult,
    SensitivityCategory,
    placeholder,
)
from neurosphere_core.classification.protocol import Detector

__all__ = [
    "ALL_CATEGORIES",
    "COVERAGE_LABEL",
    "CREDENTIAL_CATEGORIES",
    "PLACEHOLDER_RE",
    "SENSITIVITY_CATEGORY_FOR",
    "Action",
    "Category",
    "Confidence",
    "Detector",
    "Finding",
    "Match",
    "PartKind",
    "ReasonCode",
    "Redacted",
    "RedactionBudget",
    "RedactionConfig",
    "RedactionFailed",
    "RedactionMode",
    "RedactionResult",
    "SensitivityCategory",
    "placeholder",
]
