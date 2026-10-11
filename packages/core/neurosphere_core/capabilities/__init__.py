"""Capability matrix: documentation-derived, source-cited service availability (PRP-02)."""

from neurosphere_core.capabilities.loader import (
    DATA_DIR,
    CapabilityMatrix,
    MatrixLoadError,
    load_matrix,
    matrix_from_rows,
)
from neurosphere_core.capabilities.validate import (
    STALE_AFTER_DAYS,
    CapabilityResult,
    DeploymentProfile,
    FeatureRequest,
    ProfileResult,
    default_matrix,
    validate_profile,
)

__all__ = [
    "DATA_DIR",
    "STALE_AFTER_DAYS",
    "CapabilityMatrix",
    "CapabilityResult",
    "DeploymentProfile",
    "FeatureRequest",
    "MatrixLoadError",
    "ProfileResult",
    "default_matrix",
    "load_matrix",
    "matrix_from_rows",
    "validate_profile",
]
