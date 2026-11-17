"""Map AWS SDK failures to the NeuroSphere error taxonomy without importing the SDK.

Only the AWS error *code* and HTTP status are read; the AWS message is never copied into an
exception, a log or a health report (it can echo request parameters). Duck typing on
``exc.response`` keeps this module importable, and testable, without boto3 installed.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

from neurosphere_core.errors import (
    DependencyTransientError,
    ForbiddenError,
    NeuroSphereError,
    RateLimitedError,
    UnauthorizedError,
)

__all__ = ["call_with_backoff", "map_aws_error"]

#: Throttling codes. ``LimitExceededException`` is what Cost Explorer returns for "too many calls".
THROTTLE_CODES = frozenset(
    {
        "Throttling",
        "ThrottlingException",
        "ThrottledException",
        "TooManyRequestsException",
        "RequestLimitExceeded",
        "LimitExceededException",
        "ProvisionedThroughputExceededException",
        "RequestThrottled",
    }
)
_DENIED_CODES = frozenset({"AccessDenied", "AccessDeniedException", "UnauthorizedOperation"})
_AUTH_CODES = frozenset(
    {
        "ExpiredToken",
        "ExpiredTokenException",
        "InvalidClientTokenId",
        "UnrecognizedClientException",
        "InvalidSignatureException",
        "SignatureDoesNotMatch",
        "IDPRejectedClaim",
        "InvalidIdentityToken",
        "NotAuthorized",
    }
)
_RETRY_AFTER_DEFAULT = 5


def _code_and_status(exc: BaseException) -> tuple[str | None, int | None]:
    response: Any = getattr(exc, "response", None)
    if not isinstance(response, dict):
        return None, None
    err: Any = response.get("Error")  # pyright: ignore[reportUnknownMemberType]
    meta: Any = response.get("ResponseMetadata")  # pyright: ignore[reportUnknownMemberType]
    code = err.get("Code") if isinstance(err, dict) else None  # pyright: ignore[reportUnknownMemberType]
    status = meta.get("HTTPStatusCode") if isinstance(meta, dict) else None  # pyright: ignore[reportUnknownMemberType]
    return (
        code if isinstance(code, str) else None,
        status if isinstance(status, int) else None,
    )


def map_aws_error(exc: BaseException) -> NeuroSphereError:
    """Return the typed error for one SDK exception. Never includes the AWS message."""
    if isinstance(exc, NeuroSphereError):
        return exc
    code, status = _code_and_status(exc)
    if code in THROTTLE_CODES or status == 429:
        return RateLimitedError(_RETRY_AFTER_DEFAULT, reason="aws_throttled")
    if code in _DENIED_CODES or status == 403:
        return ForbiddenError(reason="aws_access_denied")
    if code in _AUTH_CODES or status == 401:
        return UnauthorizedError(reason="aws_credentials_rejected")
    if status is not None and status >= 500:
        return DependencyTransientError(reason="aws_unavailable")
    if code is None and status is None:
        # No HTTP response at all: connect, DNS or timeout failure inside the SDK.
        return DependencyTransientError(reason="aws_unreachable")
    return DependencyTransientError(reason="aws_request_rejected", upstream_invalid=True)


async def call_with_backoff[T](
    operation: Callable[[], Awaitable[T]],
    *,
    max_attempts: int,
    base_delay: float,
    cap_delay: float,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> T:
    """Retry rate-limited and transient failures with capped exponential backoff.

    Never more than ``max_attempts`` calls; every other error class is raised at once.
    """
    attempt = 0
    while True:
        attempt += 1
        try:
            return await operation()
        except (RateLimitedError, DependencyTransientError):
            if attempt >= max_attempts:
                raise
        await sleep(min(cap_delay, base_delay * (2 ** (attempt - 1))))
