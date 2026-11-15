"""``GET /api/v1/audit/siem/status`` (PRP-40 item 4): the SIEM sink's configuration and health.

Needs ``audit.read`` on the customer control domain (the sink carries every domain's events).
The body is :class:`~neurosphere_api.audit.models.AuditSiemStatus`: sink kind, composition state
and reason code, last success and failure times, counters and the last failure reason CODE.
Never a host, hub name, key or exception text (``SiemSinkHealth`` keeps none of them).

No ``from __future__ import annotations``: FastAPI inspects these signatures.
"""

from dataclasses import asdict
from typing import Annotated, Final

from fastapi import APIRouter, Depends, Request
from neurosphere_core.audit.siem_health import SiemSinkHealth
from neurosphere_core.auth.scope import Permission
from neurosphere_core.scope import IdentityScope

from neurosphere_api.audit.access import require_customer_wide
from neurosphere_api.audit.models import AuditSiemStatus

__all__ = ["PREFIX", "build_router"]

PREFIX: Final = "/api/v1/audit/siem"


def build_router() -> APIRouter:
    router = APIRouter(tags=["audit"])

    @router.get("/status", response_model=AuditSiemStatus)
    async def audit_siem_status(
        request: Request,
        scope: Annotated[IdentityScope, Depends(require_customer_wide(Permission.AUDIT_READ))],
    ) -> AuditSiemStatus:
        del scope  # authorization only
        health = getattr(request.app.state, "siem_sink_health", None)
        if not isinstance(health, SiemSinkHealth):
            return AuditSiemStatus(sink="none", state="not_built")
        return AuditSiemStatus.model_validate(asdict(health.snapshot()))

    return router
