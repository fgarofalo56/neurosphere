"""Lifecycle API (PRP-23 round 2 item 3): legal holds, deletion requests and status.

Wiring: ``neurosphere_api.lifecycle.register(registry)`` mounts ``/api/v1/lifecycle`` and the
``lifecycle`` builder installs a :class:`LifecycleApiState` on ``app.state.lifecycle``. The API
only persists jobs and holds; the lifecycle worker runs them (dry-run unless
``NS_LIFECYCLE_MODE=execute``).
"""

from neurosphere_api.lifecycle.router import PREFIX, build_router, get_lifecycle, register
from neurosphere_api.lifecycle.state import STATE_ATTRIBUTE, LifecycleApiState

__all__ = [
    "PREFIX",
    "STATE_ATTRIBUTE",
    "LifecycleApiState",
    "build_router",
    "get_lifecycle",
    "register",
]
