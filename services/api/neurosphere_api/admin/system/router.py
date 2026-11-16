"""System status and first-run checklist routes, at ``/api/v1/admin/system`` (PRP-45 item 2).

| Method | Path          | Notes                                                             |
|--------|---------------|-------------------------------------------------------------------|
| GET    | ``/status``   | every registry component and step, environment probe codes         |
| GET    | ``/checklist``| first-run checklist (``checklist.py``)                              |

Both need the deployment-scoped admin (``config.manage`` on the control domain). Bodies carry
component names, states and reason codes only, the ``/readyz`` rule: never a configuration
value, host or secret.

No ``from __future__ import annotations``: FastAPI inspects these signatures.
"""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from neurosphere_core.admin.runtime import StoredSettingsSnapshot
from neurosphere_core.errors import DependencyTransientError

from neurosphere_api.admin.system.checklist import build_checklist
from neurosphere_api.admin.system.deps import AdminScope
from neurosphere_api.admin.system.models import (
    ChecklistPage,
    ComponentView,
    StoredSettingsState,
    SystemStatus,
)
from neurosphere_api.admin.system.service import SystemAdminPlane, get_plane
from neurosphere_api.health.probes import run_probes, timeout_from_env
from neurosphere_api.runtime.readiness import COMPOSITION_PROBE
from neurosphere_api.runtime.status import ComponentRegistry

__all__ = ["build_router", "stored_state"]

Plane = Annotated[SystemAdminPlane, Depends(get_plane)]


def _registry(request: Request) -> ComponentRegistry:
    registry = getattr(request.app.state, "composition", None)
    if not isinstance(registry, ComponentRegistry):
        raise DependencyTransientError(
            "the application was not composed", reason="composition_unavailable"
        )
    return registry


def stored_state(snapshot: StoredSettingsSnapshot) -> StoredSettingsState:
    return StoredSettingsState(
        status=snapshot.status, reason=snapshot.reason, invalid_keys=sorted(snapshot.invalid)
    )


async def _probes(request: Request, plane: SystemAdminPlane) -> dict[str, str]:
    state = request.app.state
    probes = getattr(state, "health_probes", None) or ()
    env = tuple(
        p
        for p in probes
        if p.name != COMPOSITION_PROBE and not p.name.startswith(f"{COMPOSITION_PROBE}.")
    )
    if not env:
        return {}
    timeout: Any = getattr(state, "health_timeout", None)
    limit = float(timeout) if timeout is not None else timeout_from_env(plane.environ)
    return dict(await run_probes(env, limit))


def _registered_write_targets(request: Request) -> tuple[str, ...]:
    registry = getattr(request.app.state, "write_targets", None)
    names: Any = getattr(registry, "names", None)
    if not callable(names):
        return ()
    found: Any = names()
    return tuple(str(n) for n in found)


def build_router() -> APIRouter:
    router = APIRouter(tags=["admin-system"])

    @router.get("/status", response_model=SystemStatus)
    async def system_status(request: Request, _scope: AdminScope, plane: Plane) -> SystemStatus:
        registry = _registry(request)
        components = [
            ComponentView(
                name=s.name,
                state=s.state,
                required=s.required,
                reason=s.reason if s.state == "failed" else None,
                blocks_readiness=s.blocks_readiness,
                step=s.step,
            )
            for s in registry.snapshot()
        ]
        return SystemStatus(
            ready=registry.ready,
            components=components,
            probes=await _probes(request, plane),
            stored_settings=stored_state(plane.applied),
        )

    @router.get("/checklist", response_model=ChecklistPage)
    async def system_checklist(request: Request, _scope: AdminScope, plane: Plane) -> ChecklistPage:
        items = build_checklist(
            _registry(request),
            plane.applied,
            registered_write_targets=_registered_write_targets(request),
            customer_binding=plane.customer_binding,
        )
        return ChecklistPage(items=items)

    return router
