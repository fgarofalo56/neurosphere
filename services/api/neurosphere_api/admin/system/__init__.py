"""System administration API (PRP-45), mounted at ``/api/v1/admin/system``.

* ``/status`` and ``/checklist``: what is configured, what is off and why, what to do next,
  derived from the same component registry ``/readyz`` reads (``router.py``, ``checklist.py``);
* ``/settings``: stored runtime settings (copilot, judge, search, scan, MCP server, write
  targets) that the builders read at startup over env (``settings_router.py``, ``stored.py``).

Every route needs the deployment-scoped admin (``config.manage`` on the control domain).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from neurosphere_api.routers import RouterRegistry

__all__ = ["PREFIX", "register"]

PREFIX: Final = "/api/v1/admin/system"


def register(registry: RouterRegistry) -> None:
    """Router-registry hook (``neurosphere_api/routers.py``)."""
    from neurosphere_api.admin.system import router, settings_router

    registry.register(PREFIX, router.build_router())
    registry.register(f"{PREFIX}/settings", settings_router.build_router())
