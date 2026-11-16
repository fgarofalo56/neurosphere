"""``/healthz`` (liveness) and ``/readyz`` (readiness, fail closed)."""

from __future__ import annotations

import os
from collections.abc import Mapping
from typing import Final, Literal

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict

from neurosphere_api.health.probes import (
    DependencyProbe,
    ReasonCode,
    probes_from_env,
    run_probes,
    timeout_from_env,
)
from neurosphere_api.routers import RouterRegistry

#: ``NS_READYZ_DETAIL``: ``full`` (default) lists every dependency and component reason code;
#: ``summary`` lists only the aggregate ``composition`` entry. Any other value is treated as
#: ``summary`` (fail closed: never expose more than asked).
READYZ_DETAIL_ENV: Final = "NS_READYZ_DETAIL"
SUMMARY_KEY: Final = "composition"


def readyz_detail_from_env(env: Mapping[str, str]) -> Literal["full", "summary"]:
    value = env.get(READYZ_DETAIL_ENV, "").strip().lower()
    if value in ("", "full"):
        return "full"
    return "summary"


class HealthzResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["ok"]


class ReadyzResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["ready", "not_ready"]
    dependencies: dict[str, ReasonCode]


def _probes_for(request: Request) -> tuple[tuple[DependencyProbe, ...], float]:
    """``app.state.health_probes`` / ``health_timeout`` override the environment (tests)."""
    state = request.app.state
    probes = getattr(state, "health_probes", None)
    timeout = getattr(state, "health_timeout", None)
    env = dict(os.environ)
    return (
        tuple(probes) if probes is not None else probes_from_env(env),
        float(timeout) if timeout is not None else timeout_from_env(env),
    )


def build_router() -> APIRouter:
    router = APIRouter(tags=["health"])

    @router.get("/healthz", response_model=HealthzResponse)
    async def healthz() -> HealthzResponse:
        return HealthzResponse(status="ok")

    @router.get(
        "/readyz",
        response_model=ReadyzResponse,
        responses={503: {"model": ReadyzResponse, "description": "A dependency is not ready."}},
    )
    async def readyz(request: Request) -> JSONResponse:
        probes, timeout = _probes_for(request)
        results: dict[str, ReasonCode] = dict(await run_probes(probes, timeout))
        ready = all(code == "ok" for code in results.values())
        if readyz_detail_from_env(os.environ) == "summary":
            results = {k: v for k, v in results.items() if k == SUMMARY_KEY}
        body = ReadyzResponse(status="ready" if ready else "not_ready", dependencies=results)
        return JSONResponse(body.model_dump(), status_code=200 if ready else 503)

    return router


def register(registry: RouterRegistry) -> None:
    registry.register("", build_router())
