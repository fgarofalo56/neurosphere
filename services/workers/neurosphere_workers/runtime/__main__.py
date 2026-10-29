"""``python -m neurosphere_workers.runtime``: the roles in ``NS_WORKER_ROLES`` plus health.

``NS_WORKER_ROLES`` is a comma list of ingestion, projections, aggregates, actions, hitl_timers,
lifecycle, recommendations, evaluation, gateway_poll (opt-in: not part of ``all``), or ``all``.
Unset means idle (health only, ``roles: []``).
An unknown role refuses to start (exit 2). Every role runs as a supervised task: a crash restarts
that role with backoff and marks readiness failed without touching the others.
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from collections.abc import Mapping

from neurosphere_workers.runtime.factories import (
    BUILDERS,
    RoleBuilder,
    RuntimeConfig,
    role_factories,
)
from neurosphere_workers.runtime.health import HealthServer
from neurosphere_workers.runtime.roles import UnknownRoleError, parse_roles
from neurosphere_workers.runtime.signals import install_signal_handlers
from neurosphere_workers.runtime.supervisor import RoleSupervisor

logger = logging.getLogger("neurosphere.workers.runtime")

EXIT_USAGE = 2


async def _stop_on(stop: asyncio.Event, supervisor: RoleSupervisor) -> None:
    await stop.wait()
    supervisor.request_shutdown()


async def run_roles(
    roles: tuple[str, ...],
    cfg: RuntimeConfig,
    *,
    builders: Mapping[str, RoleBuilder] = BUILDERS,
    handle_signals: bool = True,
    stop: asyncio.Event | None = None,
) -> int:
    """Run ``roles`` and the health server until SIGTERM/SIGINT (or ``stop``); the exit code."""
    supervisor = RoleSupervisor(role_factories(cfg, roles, builders))
    health = HealthServer(
        lambda: supervisor.status,
        cfg.worker.health_host,
        cfg.worker.health_port,
        roles_provider=supervisor.snapshot,
        ready_provider=lambda: supervisor.ready,
    )
    uninstall = install_signal_handlers(supervisor.request_shutdown) if handle_signals else None
    await health.start()
    stopper = None if stop is None else asyncio.create_task(_stop_on(stop, supervisor))
    logger.info("worker started", extra={"event": "worker.started", "roles": list(roles)})
    try:
        await supervisor.run()
    finally:
        if stopper is not None:
            stopper.cancel()
        if uninstall is not None:
            uninstall()
        await health.stop()
    logger.info("worker stopped", extra={"event": "worker.stopped"})
    return 0


async def _amain(raw_roles: str | None) -> int:
    cfg = RuntimeConfig.from_env()
    return await run_roles(parse_roles(raw_roles), cfg)


def main(raw_roles: str | None = None) -> int:
    """Entry point. ``raw_roles`` overrides ``NS_WORKER_ROLES`` (the ingestion alias uses it)."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    if os.environ.get("NS_LOG_LEVEL", "").strip().upper() != "DEBUG":
        # The Azure SDK logs every HTTP request/response at INFO; keep it to warnings.
        logging.getLogger("azure").setLevel(logging.WARNING)
    selected = raw_roles if raw_roles is not None else os.environ.get("NS_WORKER_ROLES")
    try:
        parse_roles(selected)
    except UnknownRoleError as exc:
        logger.error("refusing to start: %s", exc)
        return EXIT_USAGE
    return asyncio.run(_amain(selected))


if __name__ == "__main__":
    sys.exit(main())
