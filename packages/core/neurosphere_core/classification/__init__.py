"""Sensitive-information detectors and typed redaction (PRP-101).

Pure; structured identifiers only.
"""

from __future__ import annotations

from neurosphere_core.classification.detector_set import (
    DEFAULT_SET_VERSION,
    DetectorSet,
    default_detector_set,
)
from neurosphere_core.classification.detectors.customer import (
    CustomerDictionary,
    CustomerPattern,
    PatternRefused,
    build_customer_detectors,
)
from neurosphere_core.classification.detectors.identifiers import identifier_detectors
from neurosphere_core.classification.detectors.secret_detectors import secret_detectors
from neurosphere_core.classification.engine import redact
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
    "DEFAULT_SET_VERSION",
    "PLACEHOLDER_RE",
    "SENSITIVITY_CATEGORY_FOR",
    "Action",
    "Category",
    "Confidence",
    "CustomerDictionary",
    "CustomerPattern",
    "Detector",
    "DetectorSet",
    "Finding",
    "Match",
    "PartKind",
    "PatternRefused",
    "ReasonCode",
    "Redacted",
    "RedactionBudget",
    "RedactionConfig",
    "RedactionFailed",
    "RedactionMode",
    "RedactionResult",
    "SensitivityCategory",
    "build_customer_detectors",
    "default_detector_set",
    "identifier_detectors",
    "placeholder",
    "redact",
    "secret_detectors",
]
