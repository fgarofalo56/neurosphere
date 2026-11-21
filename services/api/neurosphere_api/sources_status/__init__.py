"""Source status API (PRP-139 item 3): ``GET /api/v1/sources/status`` and
``GET /api/v1/admin/sources/status``."""

from __future__ import annotations

from typing import TYPE_CHECKING

from neurosphere_api.sources_status.service import (
    STATE_ATTRIBUTE,
    SourceStatusPlane,
    configure_source_status,
)

if TYPE_CHECKING:
    from neurosphere_api.routers import RouterRegistry

__all__ = [
    "STATE_ATTRIBUTE",
    "SourceStatusPlane",
    "configure_source_status",
    "register",
]


def register(registry: RouterRegistry) -> None:
    """Router-registry hook (``neurosphere_api/routers.py``)."""
    from neurosphere_api.sources_status.router import (
        ADMIN_PREFIX,
        USER_PREFIX,
        build_admin_router,
        build_user_router,
    )

    registry.register(USER_PREFIX, build_user_router())
    registry.register(ADMIN_PREFIX, build_admin_router())
