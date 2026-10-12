"""Exception classes for the seven PRP-01 error codes.

``http_status`` and ``retryable`` are class constants that tests cross-check against
``error-codes.json`` and the generated ``ProblemDetails`` model. ``to_problem_details`` renders
the contract body; no stack traces, query text or secrets are ever placed in it.
"""

from __future__ import annotations

from typing import ClassVar, Literal

from neurosphere_contracts.errors.v1.problem_details import ProblemDetails
from neurosphere_contracts.errors.v1.problem_details import ValidationError as _ContractIssue

ErrorCode = Literal[
    "unauthorized",
    "forbidden",
    "capability_unavailable",
    "stale_version",
    "rate_limited",
    "invalid_schema",
    "dependency_transient",
]
HttpStatus = Literal[401, 403, 409, 422, 429, 502, 503]

_SCHEMA_VERSION = "1.0.0"
_PROBLEM_TYPE_BASE = "https://neurosphere.invalid/problems/"


class ValidationIssue:
    """One invalid_schema member failure (RFC 6901 pointer plus a value-free message)."""

    __slots__ = ("detail", "pointer")

    def __init__(self, pointer: str, detail: str) -> None:
        self.pointer = pointer
        self.detail = detail


class NeuroSphereError(Exception):
    """Base class. Subclasses fix ``code``, ``title``, ``http_status`` and ``retryable``."""

    code: ClassVar[ErrorCode]
    title: ClassVar[str]
    http_status: ClassVar[HttpStatus]
    retryable: ClassVar[bool]

    def __init__(
        self,
        detail: str | None = None,
        *,
        reason: str | None = None,
        retry_after_seconds: int | None = None,
    ) -> None:
        super().__init__(detail or self.title)
        if retry_after_seconds is not None and not self.retryable:
            # Contract rule the generated model cannot express (allOf if/then).
            raise ValueError(f"retry_after_seconds is not allowed for {self.code}")
        self.detail = detail
        self.reason = reason
        self.retry_after_seconds = retry_after_seconds
        self.errors: tuple[ValidationIssue, ...] | None = None

    @property
    def status(self) -> HttpStatus:
        """HTTP status for this instance (instance-level so 502 can be selected)."""
        return self.http_status

    def to_problem_details(
        self, correlation_id: str, *, instance: str | None = None
    ) -> ProblemDetails:
        """Render and validate the contract body; invalid combinations raise at render time."""
        return ProblemDetails(
            schema_version=_SCHEMA_VERSION,
            type=f"{_PROBLEM_TYPE_BASE}{self.code}",
            title=self.title,
            status=self.status,
            detail=self.detail,
            instance=instance,
            code=self.code,
            retryable=self.retryable,
            correlation_id=correlation_id,
            reason=self.reason,
            retry_after_seconds=self.retry_after_seconds,
            errors=(
                [_ContractIssue(pointer=i.pointer, detail=i.detail) for i in self.errors]
                if self.errors
                else None
            ),
        )


class UnauthorizedError(NeuroSphereError):
    code = "unauthorized"
    title = "Unauthorized"
    http_status = 401
    retryable = False


class ForbiddenError(NeuroSphereError):
    code = "forbidden"
    title = "Forbidden"
    http_status = 403
    retryable = False


class CapabilityUnavailableError(NeuroSphereError):
    code = "capability_unavailable"
    title = "Capability unavailable"
    http_status = 409
    retryable = False

    def __init__(self, reason: str, detail: str | None = None) -> None:
        super().__init__(detail, reason=reason)


class StaleVersionError(NeuroSphereError):
    code = "stale_version"
    title = "Stale version"
    http_status = 409
    retryable = False


class RateLimitedError(NeuroSphereError):
    code = "rate_limited"
    title = "Rate limited"
    http_status = 429
    retryable = True

    def __init__(
        self, retry_after_seconds: int, detail: str | None = None, *, reason: str | None = None
    ) -> None:
        super().__init__(detail, reason=reason, retry_after_seconds=retry_after_seconds)


class InvalidSchemaError(NeuroSphereError):
    code = "invalid_schema"
    title = "Invalid schema"
    http_status = 422
    retryable = False

    def __init__(
        self,
        detail: str | None = None,
        *,
        errors: tuple[ValidationIssue, ...] | list[ValidationIssue] | None = None,
        reason: str | None = None,
    ) -> None:
        super().__init__(detail, reason=reason)
        self.errors = tuple(errors) if errors else None


class DependencyTransientError(NeuroSphereError):
    """503 by default; 502 (``upstream_invalid=True``) when an upstream returned a bad response."""

    code = "dependency_transient"
    title = "Dependency temporarily unavailable"
    http_status = 503
    retryable = True

    def __init__(
        self,
        detail: str | None = None,
        *,
        reason: str | None = None,
        retry_after_seconds: int | None = None,
        upstream_invalid: bool = False,
    ) -> None:
        super().__init__(detail, reason=reason, retry_after_seconds=retry_after_seconds)
        self._status: HttpStatus = 502 if upstream_invalid else 503

    @property
    def status(self) -> HttpStatus:
        return self._status
