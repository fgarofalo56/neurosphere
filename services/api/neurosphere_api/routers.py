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


def _register_actions(registry: RouterRegistry) -> None:
    from neurosphere_api.actions import register

    register(registry)


def _register_hitl(registry: RouterRegistry) -> None:
    from neurosphere_api.hitl import register

    register(registry)


def _register_realtime(registry: RouterRegistry) -> None:
    from neurosphere_api.realtime import register

    register(registry)


def _register_map(registry: RouterRegistry) -> None:
    from neurosphere_api.map import register

    register(registry)


def _register_replay(registry: RouterRegistry) -> None:
    from neurosphere_api.replay import register

    register(registry)


def _register_copilot(registry: RouterRegistry) -> None:
    from neurosphere_api.copilot import register

    register(registry)


def _register_reports(registry: RouterRegistry) -> None:
    from neurosphere_api.reports import register

    register(registry)


def _register_me(registry: RouterRegistry) -> None:
    from neurosphere_api.me import register

    register(registry)


def _register_workspaces(registry: RouterRegistry) -> None:
    from neurosphere_api.workspaces import register

    register(registry)


def _register_federation(registry: RouterRegistry) -> None:
    from neurosphere_api.federation import register

    register(registry)


def _register_finops(registry: RouterRegistry) -> None:
    from neurosphere_api.finops import register

    register(registry)


def _register_mcp_server(registry: RouterRegistry) -> None:
    from neurosphere_api.mcp.server import register

    register(registry)


def _register_mcp_admin(registry: RouterRegistry) -> None:
    from neurosphere_api.mcp.admin import register

    register(registry)


def _register_sandbox(registry: RouterRegistry) -> None:
    from neurosphere_api.sandbox import register

    register(registry)


def _register_gateway(registry: RouterRegistry) -> None:
    from neurosphere_api.gateway import register

    register(registry)


def _register_ui_adapters(registry: RouterRegistry) -> None:
    from neurosphere_api.ui_adapters import register

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
    _register_actions,
    _register_hitl,
    _register_realtime,
    _register_map,
    _register_replay,
    _register_copilot,
    _register_reports,
    _register_me,
    _register_workspaces,
    _register_federation,
    _register_finops,
    _register_mcp_server,
    _register_mcp_admin,
    _register_sandbox,
    _register_gateway,
    _register_ui_adapters,
)


def register_default_routers(registry: RouterRegistry) -> None:
    for hook in REGISTERED:
        hook(registry)
