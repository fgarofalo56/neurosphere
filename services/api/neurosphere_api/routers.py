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
        self._defaults: set[str] = set()

    @staticmethod
    def _normalize(prefix: str) -> str:
        stripped = prefix.strip().rstrip("/")
        if stripped and not stripped.startswith("/"):
            stripped = "/" + stripped
        return stripped

    def freeze_defaults(self) -> None:
        """Mark the current prefixes as defaults that a caller router may replace once."""
        self._defaults = set(self._routers)

    def register(self, prefix: str, router: APIRouter, *, replace_default: bool = False) -> None:
        key = self._normalize(prefix)
        if key in self._routers:
            if not (replace_default and key in self._defaults):
                raise ValueError(f"router prefix already registered: {key or '/'}")
            self._defaults.discard(key)
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


def _register_audit(registry: RouterRegistry) -> None:
    from neurosphere_api.audit import register
    from neurosphere_api.authz import audit_require_permission, domain_from_chain_id

    register(
        registry, require_permission=audit_require_permission(chain_domain=domain_from_chain_id)
    )


def _register_ingest(registry: RouterRegistry) -> None:
    from neurosphere_api.ingest import register

    register(registry)


def _register_deploy_scan(registry: RouterRegistry) -> None:
    from neurosphere_api.deploy.scan import register

    register(registry)


def _register_deploy_plan(registry: RouterRegistry) -> None:
    from neurosphere_api.deploy.plan import register

    register(registry)


def _register_catalog(registry: RouterRegistry) -> None:
    from neurosphere_api.catalog import register

    register(registry)


def _register_catalog_curation(registry: RouterRegistry) -> None:
    from neurosphere_api.catalog.curation import register

    register(registry)


def _register_dashboards(registry: RouterRegistry) -> None:
    from neurosphere_api.dashboards import register

    register(registry)


def _register_reconciliation(registry: RouterRegistry) -> None:
    from neurosphere_api.reconciliation import register

    register(registry)


def _register_recommendations(registry: RouterRegistry) -> None:
    from neurosphere_api.recommendations import register

    register(registry)


def _register_evaluation(registry: RouterRegistry) -> None:
    from neurosphere_api.evaluation import register

    register(registry)


REGISTERED: tuple[RegisterHook, ...] = (
    _register_health,
    _register_audit,
    _register_ingest,
    _register_deploy_scan,
    _register_deploy_plan,
    _register_catalog,
    _register_catalog_curation,
    _register_dashboards,
    _register_reconciliation,
    _register_recommendations,
    _register_evaluation,
)


def register_default_routers(registry: RouterRegistry) -> None:
    for hook in REGISTERED:
        hook(registry)
