"""ASGI middleware and error rendering for the API application."""

from neurosphere_api.middleware.correlation import (
    CORRELATION_HEADER,
    CorrelationIdMiddleware,
    correlation_id_of,
)
from neurosphere_api.middleware.problem import generic_problem_response, problem_response
from neurosphere_api.middleware.size_limit import (
    DEFAULT_MAX_REQUEST_BYTES,
    RequestSizeLimitMiddleware,
)

__all__ = [
    "CORRELATION_HEADER",
    "DEFAULT_MAX_REQUEST_BYTES",
    "CorrelationIdMiddleware",
    "RequestSizeLimitMiddleware",
    "correlation_id_of",
    "generic_problem_response",
    "problem_response",
]
