"""Read-only capture admin routes, mounted at ``/api/v1/admin/interactions`` (PRP-103 item 5).

| Method | Path                                 | Who                                             |
|--------|--------------------------------------|-------------------------------------------------|
| GET    | ``/capture-policies``                | ``config.manage`` in ``domain_id``; customer-   |
|        |                                      | level ``config.manage`` without ``domain_id``   |
| GET    | ``/capture-policies/{policy_id}``    | ``config.manage`` on the policy's domain (or    |
|        |                                      | customer-level); otherwise 404 like unknown     |
| GET    | ``/capture-status``                  | as the list; counters for customer-wide only    |

There is no write route: a capture policy changes only through an approved
``capture_policy_change`` action (PRP-108's handler calls ``apply_capture_policy_change``).
Responses are metadata and counters only (see ``models``).

No ``from __future__ import annotations``: FastAPI inspects these signatures.
"""

from typing import Annotated, Final

from fastapi import APIRouter, Depends, Path, Query, Request, Response

from neurosphere_api.admin.capture.models import (
    DEFAULT_PAGE_LIMIT,
    MAX_PAGE_LIMIT,
    NOT_CONFIGURED,
    CapturePolicyPage,
    CapturePolicyView,
    CaptureStatusView,
)
from neurosphere_api.admin.capture.service import (
    POLICY_ID_PATTERN,
    CaptureReadScope,
    capture_policy_reader,
    capture_read_scope,
    get_policy,
    list_policies,
    read_status,
)
from neurosphere_api.authz import AuthzState, get_authz_state
from neurosphere_api.routers import RouterRegistry

__all__ = ["PREFIX", "build_router", "register"]

PREFIX: Final = "/api/v1/admin/interactions"

ReadScope = Annotated[CaptureReadScope, Depends(capture_read_scope)]
PolicyReader = Annotated[CaptureReadScope, Depends(capture_policy_reader)]
PolicyPath = Annotated[str, Path(pattern=POLICY_ID_PATTERN, max_length=64)]

_LIST_DESCRIPTION: Final = (
    "Capture policies (metadata only): scope, sources, parts, redaction mode, kept categories, "
    "sampling, retention, state, version and the approval audit id. With `domain_id`, "
    "`config.manage` in that domain; without it, customer-level `config.manage`. Read-only: "
    "changes are `capture_policy_change` actions."
)
_GET_DESCRIPTION: Final = (
    "One capture policy (metadata only). `config.manage` on the policy's domain or "
    "customer-level; a policy the caller may not read is 404 like an unknown one."
)
_STATUS_DESCRIPTION: Final = (
    "Whether interaction capture is on, the off reason code when it is off, policy counts per "
    "state and, for customer-level callers, the deployment-wide counters (captured, skipped, "
    "failed by reason, shed). Reason `capture_not_configured` when capture was not composed."
)


def _no_store(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"


def build_router() -> APIRouter:
    router = APIRouter(tags=["admin-capture"])

    @router.get(
        "/capture-policies", response_model=CapturePolicyPage, description=_LIST_DESCRIPTION
    )
    async def list_capture_policies(
        request: Request,
        response: Response,
        read: ReadScope,
        limit: Annotated[int, Query(ge=1, le=MAX_PAGE_LIMIT)] = DEFAULT_PAGE_LIMIT,
    ) -> CapturePolicyPage:
        _no_store(response)
        items, truncated, configured = await list_policies(request, read, limit)
        return CapturePolicyPage(
            items=items,
            truncated=truncated,
            configured=configured,
            reason=None if configured else NOT_CONFIGURED,
        )

    @router.get(
        "/capture-policies/{policy_id}",
        response_model=CapturePolicyView,
        description=_GET_DESCRIPTION,
    )
    async def get_capture_policy(
        request: Request,
        response: Response,
        policy_id: PolicyPath,
        read: PolicyReader,
        state: Annotated[AuthzState, Depends(get_authz_state)],
    ) -> CapturePolicyView:
        _no_store(response)
        return await get_policy(request, state, read, policy_id)

    @router.get(
        "/capture-status", response_model=CaptureStatusView, description=_STATUS_DESCRIPTION
    )
    async def capture_status(
        request: Request, response: Response, read: ReadScope
    ) -> CaptureStatusView:
        _no_store(response)
        return await read_status(request, read)

    return router


def register(registry: RouterRegistry) -> None:
    """Router-registry hook (see ``neurosphere_api/routers.py``)."""
    registry.register(PREFIX, build_router())
