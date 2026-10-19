"""The default app exposes the dashboards and reconciliation routes (PRP-14 item 5).

Unmarked: runs in CI. No network. The routes come from ``register_default_routers`` (the
``REGISTERED`` hooks), not from a test-supplied router, so this fails if a hook is dropped.
"""

from __future__ import annotations

import authz.authz_helpers as helpers  # pyright: ignore[reportMissingImports]
from neurosphere_api.app import create_app
from neurosphere_api.dashboards import PREFIX as DASHBOARDS_PREFIX
from neurosphere_api.reconciliation import PREFIX as RECONCILIATION_PREFIX
from neurosphere_api.routers import REGISTERED, RouterRegistry, register_default_routers
from neurosphere_core.auth.scope import Role
from neurosphere_core.cloud import Settings


def test_both_prefixes_are_in_the_default_registry() -> None:
    registry = RouterRegistry()
    register_default_routers(registry)
    assert DASHBOARDS_PREFIX in registry.prefixes
    assert RECONCILIATION_PREFIX in registry.prefixes
    assert len(registry.prefixes) == len(set(registry.prefixes))
    assert len(REGISTERED) >= 2


def test_default_app_serves_both_route_shapes() -> None:
    app = create_app(Settings(env="local"))
    paths = set(app.openapi()["paths"])
    assert f"{DASHBOARDS_PREFIX}/domains/{{domain}}/{{metric}}" in paths
    assert f"{RECONCILIATION_PREFIX}/domains/{{domain}}" in paths


def test_an_unconfigured_aggregate_reader_fails_closed_with_503() -> None:
    """The routes exist on the default app and fail closed (503), never an empty 200, until a
    deployment sets ``app.state.aggregate_reader`` (production bootstrap is recorded OPEN)."""
    h = helpers.harness(
        helpers.policy(helpers.ALICE, helpers.role(Role.VIEWER, helpers.FINANCE)),
        routers={},  # no test routers: the default hooks only
    )
    headers = h.auth(helpers.ALICE)
    dashboards = h.client.get(
        f"{DASHBOARDS_PREFIX}/domains/{helpers.FINANCE}/cost", headers=headers
    )
    reconciliation = h.client.get(
        f"{RECONCILIATION_PREFIX}/domains/{helpers.FINANCE}", headers=headers
    )
    assert dashboards.status_code == 503, dashboards.text
    assert reconciliation.status_code == 503, reconciliation.text


def test_a_domain_outside_the_scope_is_403_even_when_unconfigured() -> None:
    h = helpers.harness(
        helpers.policy(helpers.ALICE, helpers.role(Role.VIEWER, helpers.FINANCE)),
        routers={},
    )
    headers = h.auth(helpers.ALICE)
    assert (
        h.client.get(
            f"{DASHBOARDS_PREFIX}/domains/{helpers.OPERATIONS}/cost", headers=headers
        ).status_code
        == 403
    )
    assert (
        h.client.get(
            f"{RECONCILIATION_PREFIX}/domains/{helpers.OPERATIONS}", headers=headers
        ).status_code
        == 403
    )
