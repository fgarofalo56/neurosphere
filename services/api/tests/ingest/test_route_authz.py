"""Guard: the authz producer-authenticated list matches the ingest router, and each listed route
actually rejects an unauthenticated request (a listed-but-unprotected path would be a hole)."""

from __future__ import annotations

import pytest
from fastapi.routing import APIRoute
from neurosphere_api.authz import PRODUCER_AUTHENTICATED_PATHS
from neurosphere_api.ingest.router import ROUTE_PREFIX, build_router

from .conftest import Harness


def test_router_post_paths_equal_producer_authenticated_paths() -> None:
    routes = [r for r in build_router().routes if isinstance(r, APIRoute)]
    assert all(r.methods == {"POST"} for r in routes)
    assert {ROUTE_PREFIX + r.path for r in routes} == set(PRODUCER_AUTHENTICATED_PATHS)


@pytest.mark.parametrize("path", sorted(PRODUCER_AUTHENTICATED_PATHS))
def test_listed_routes_return_401_without_credential(harness: Harness, path: str) -> None:
    client = harness.client
    assert client.post(path, content=b"{}").status_code == 401
    bad = client.post(path, content=b"{}", headers={"Authorization": "Bearer nope.nope"})
    assert bad.status_code == 401
