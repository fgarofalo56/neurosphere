"""Translate SDK exceptions into the PRP-01 taxonomy. Messages never echo SDK text."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from azure.core.exceptions import (
    ClientAuthenticationError,
    HttpResponseError,
    ServiceRequestError,
    ServiceResponseError,
)
from azure.eventhub import exceptions as eh

from neurosphere_core.errors import (
    DependencyTransientError,
    ForbiddenError,
    NeuroSphereError,
    RateLimitedError,
    StaleVersionError,
)

__all__ = ["translate_sdk_error", "translating"]


def _retry_after_seconds(exc: HttpResponseError) -> int:
    headers = getattr(exc, "headers", None) or {}
    raw = headers.get("x-ms-retry-after-ms") if hasattr(headers, "get") else None
    try:
        return max(1, int(float(raw) / 1000)) if raw is not None else 1
    except (TypeError, ValueError):
        return 1


def _from_status(exc: HttpResponseError) -> NeuroSphereError | None:
    status = exc.status_code
    if status in (401, 403):
        return ForbiddenError(f"dependency denied the request (HTTP {status})")
    if status == 412:
        return StaleVersionError("precondition failed (ETag mismatch)")
    if status == 429:
        return RateLimitedError(_retry_after_seconds(exc), "dependency throttled the request")
    if status is not None and (status == 408 or status >= 500):
        return DependencyTransientError(f"dependency error (HTTP {status})", reason="http_5xx")
    return None


def translate_sdk_error(exc: BaseException) -> NeuroSphereError | None:
    """Return the taxonomy error for ``exc``, or ``None`` when it is not a mapped SDK failure."""
    if isinstance(exc, NeuroSphereError):
        return exc
    if isinstance(exc, ClientAuthenticationError | eh.AuthenticationError):
        return ForbiddenError("credential rejected by dependency")
    if isinstance(exc, HttpResponseError):
        return _from_status(exc)
    if isinstance(
        exc,
        ServiceRequestError
        | ServiceResponseError
        | eh.ConnectError
        | eh.ConnectionLostError
        | eh.OperationTimeoutError
        | eh.OwnershipLostError
        | eh.EventHubError
        | TimeoutError
        | ConnectionError,
    ):
        return DependencyTransientError("dependency unreachable or timed out", reason="connection")
    return None


@contextmanager
def translating() -> Iterator[None]:
    """Re-raise mapped SDK failures as taxonomy errors (original chained); others pass through."""
    try:
        yield
    except NeuroSphereError:
        raise
    except Exception as exc:
        mapped = translate_sdk_error(exc)
        if mapped is None:
            raise
        raise mapped from exc
