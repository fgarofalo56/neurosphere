"""Render error bodies as ``application/problem+json``.

Taxonomy errors render the PRP-01 ``ProblemDetails`` contract. The contract has no codes for
404, 405 or 500, so :func:`generic_problem_response` emits a minimal RFC 9457 body (no ``code``,
no new taxonomy name, C13) that still carries ``correlation_id`` and never any trace or host.
"""

from __future__ import annotations

from http import HTTPStatus

from neurosphere_core.errors import NeuroSphereError
from starlette.responses import JSONResponse

from neurosphere_api.middleware.correlation import CORRELATION_HEADER

PROBLEM_MEDIA_TYPE = "application/problem+json"


def problem_response(error: NeuroSphereError, correlation_id: str, instance: str) -> JSONResponse:
    body = error.to_problem_details(correlation_id, instance=instance)
    headers = {CORRELATION_HEADER: correlation_id}
    if error.retry_after_seconds is not None:
        headers["retry-after"] = str(error.retry_after_seconds)
    return JSONResponse(
        body.model_dump(mode="json", exclude_none=True),
        status_code=error.status,
        media_type=PROBLEM_MEDIA_TYPE,
        headers=headers,
    )


def generic_problem_response(
    status_code: int, correlation_id: str, instance: str, detail: str | None = None
) -> JSONResponse:
    title = HTTPStatus(status_code).phrase
    body: dict[str, object] = {
        "type": "about:blank",
        "title": title,
        "status": status_code,
        "instance": instance,
        "correlation_id": correlation_id,
    }
    if detail:
        body["detail"] = detail
    return JSONResponse(
        body,
        status_code=status_code,
        media_type=PROBLEM_MEDIA_TYPE,
        headers={CORRELATION_HEADER: correlation_id},
    )
