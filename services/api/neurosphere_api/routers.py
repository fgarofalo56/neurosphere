"""Router registry: the only way modules attach routers to the API application.

``RouterRegistry.register(prefix, router)`` rejects two routers claiming the same prefix.
``create_app`` builds a registry, calls :func:`register_default_routers`, then attaches every
router. Other items add their routers by appending a ``register(registry)`` hook function to
``REGISTERED`` below (PRP-05 item 5 adds the health router here) without editing ``app.py``.
"""

from __future__ import annotations

from collections.abc import Callable

from fastapi import APIRouter, FastAPI


class RouterRegistry:
    """Collects ``(prefix, router)`` pairs; duplicate prefixes are a startup error."""

    def __init__(self) -> None:
        self._routers: dict[str, APIRouter] = {}

    @staticmethod
    def _normalize(prefix: str) -> str:
        stripped = prefix.strip().rstrip("/")
        if stripped and not stripped.startswith("/"):
            stripped = "/" + stripped
        return stripped

    def register(self, prefix: str, router: APIRouter) -> None:
        key = self._normalize(prefix)
        if key in self._routers:
            raise ValueError(f"router prefix already registered: {key or '/'}")
        self._routers[key] = router

    @property
    def prefixes(self) -> tuple[str, ...]:
        return tuple(self._routers)

    def attach(self, app: FastAPI) -> None:
        for prefix, router in self._routers.items():
            app.include_router(router, prefix=prefix)


RegisterHook = Callable[[RouterRegistry], None]


# Module hooks, each ``def register(registry: RouterRegistry) -> None``. Immutable on purpose.
def _register_health(registry: RouterRegistry) -> None:
    from neurosphere_api.health import register  # local import avoids a circular import

    register(registry)


REGISTERED: tuple[RegisterHook, ...] = (_register_health,)


def register_default_routers(registry: RouterRegistry) -> None:
    for hook in REGISTERED:
        hook(registry)
