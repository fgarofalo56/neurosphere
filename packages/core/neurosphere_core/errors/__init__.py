"""PRP-01 error taxonomy as exceptions (table: contracts errors/v1/error-codes.json)."""

from neurosphere_core.errors.taxonomy import (
    CapabilityUnavailableError,
    DependencyTransientError,
    ForbiddenError,
    InternalError,
    InvalidSchemaError,
    MethodNotAllowedError,
    NeuroSphereError,
    NotFoundError,
    PayloadTooLargeError,
    RateLimitedError,
    StaleVersionError,
    UnauthorizedError,
    ValidationIssue,
)

__all__ = [
    "CapabilityUnavailableError",
    "DependencyTransientError",
    "ForbiddenError",
    "InternalError",
    "InvalidSchemaError",
    "MethodNotAllowedError",
    "NeuroSphereError",
    "NotFoundError",
    "PayloadTooLargeError",
    "RateLimitedError",
    "StaleVersionError",
    "UnauthorizedError",
    "ValidationIssue",
]
