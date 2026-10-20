"""The default app mounts ``/api/v1/recommendations`` (PRP-15 item 6).

Unmarked: runs in CI. No network. The routes come from ``register_default_routers`` (the
``REGISTERED`` hooks), not from a test-supplied router, so this fails if the hook is dropped.
"""

from __future__ import annotations

import authz.authz_helpers as helpers  # pyright: ignore[reportMissingImports]
from neurosphere_api.app import create_app
from neurosphere_api.recommendations import PREFIX
from neurosphere_api.routers import RouterRegistry, register_default_routers
from neurosphere_core.auth.scope import Role
from neurosphere_core.cloud import Settings


def test_prefix_is_in_the_default_registry() -> None:
    registry = RouterRegistry()
    register_default_routers(registry)
    assert PREFIX == "/api/v1/recommendations"
    assert PREFIX in registry.prefixes
    assert len(registry.prefixes) == len(set(registry.prefixes))


def test_create_app_mounts_the_four_routes() -> None:
    app = create_app(Settings(env="local"))
    paths = set(app.openapi()["paths"])
    assert f"{PREFIX}/domains/{{domain}}" in paths
    assert f"{PREFIX}/domains/{{domain}}/items/{{recommendation_id}}" in paths
    assert f"{PREFIX}/domains/{{domain}}/review-requests" in paths
    assert f"{PREFIX}/domains/{{domain}}/executions" in paths


def test_an_unconfigured_store_fails_closed_with_503() -> None:
    """The routes exist on the default app and fail closed (503), never an empty 200, until a
    deployment sets ``app.state.recommendation_store`` (production bootstrap is recorded OPEN)."""
    h = helpers.harness(
        helpers.policy(helpers.ALICE, helpers.role(Role.VIEWER, helpers.FINANCE)),
        routers={},
    )
    response = h.client.get(f"{PREFIX}/domains/{helpers.FINANCE}", headers=h.auth(helpers.ALICE))
    assert response.status_code == 503, response.text
