"""World builder for the PRP-74 item 5 map-topology ABAC tests (no tests in this module).

Reuses the PRP-06 dev-issuer harness and the map API harness from ``services/api/tests`` (put on
``sys.path`` here, because those directories have no ``__init__.py``), and adds a recording
denial hook so each negative case can assert a denial record, not just a status code.
"""

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote

_API_TESTS = Path(__file__).resolve().parents[3] / "services" / "api" / "tests"
for _path in (_API_TESTS, _API_TESTS / "map"):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from authz.authz_helpers import (  # noqa: E402  # pyright: ignore[reportMissingImports]
    ALICE,
    BOB,
    FINANCE,
    NOBODY,
    OPERATIONS,
    OTHER_CUSTOMER_FINANCE,
    RecordingDenials,
    harness,
    policy,
    pseudonymizer,
    role,
)
from map_api_helpers import (  # noqa: E402  # pyright: ignore[reportMissingImports]
    NOW,
    PREFIX,
    Api,
    agent_doc,
    agent_id,
    make_edge,
    service_doc,
    service_id,
)
from neurosphere_api.map import build_router, get_clock  # noqa: E402
from neurosphere_core.aggregates import InMemoryAggregateStore  # noqa: E402
from neurosphere_core.auth.scope import Role  # noqa: E402
from neurosphere_core.catalog.repo import InMemoryCatalogRepository  # noqa: E402

__all__ = [
    "ALICE",
    "BOB",
    "EXPIRING",
    "EXPIRY_SECONDS",
    "FINANCE",
    "NOROLE",
    "OPERATIONS",
    "OTHER_CUSTOMER_FINANCE",
    "PREFIX",
    "ROUTES",
    "STEWARD_BOTH",
    "World",
    "agent_id",
    "build",
    "call",
    "service_id",
]

NOROLE = "a1b2c3d4-5e6f-4a7b-8c9d-0e1f2a3b4c5d"
EXPIRING = "b2c3d4e5-6f7a-4b8c-9d0e-1f2a3b4c5d6e"
STEWARD_BOTH = NOBODY
EXPIRY_SECONDS = 60.0
ROUTES = ("viewport", "search", "neighborhood", "impact")


@dataclass
class World:
    api: Api
    denials: RecordingDenials


def build() -> World:
    """Alice reads Finance, Bob Operations, a steward writes both; two principals are denied:
    one holds no role at all, one holds a Finance viewer role that expires after 60 seconds."""
    denials = RecordingDenials()
    h = harness(
        policy(ALICE, role(Role.VIEWER, FINANCE)),
        policy(BOB, role(Role.VIEWER, OPERATIONS)),
        policy(STEWARD_BOTH, role(Role.DOMAIN_STEWARD, FINANCE, OPERATIONS)),
        policy(NOROLE),
        policy(EXPIRING, role(Role.VIEWER, FINANCE, expires_in=EXPIRY_SECONDS)),
        routers={PREFIX: build_router()},
        denials=denials,  # pyright: ignore[reportArgumentType]
    )
    repo = InMemoryCatalogRepository()
    store = InMemoryAggregateStore()
    h.app.state.catalog_repository = repo
    h.app.state.aggregate_reader = store
    h.app.state.map_pseudonymizer = pseudonymizer()
    h.app.dependency_overrides[get_clock] = lambda: lambda: NOW
    api = Api(h=h, repo=repo, store=store)
    api.seed()
    api.set_watermark(NOW)
    api.seed(
        agent_doc("fin", FINANCE),
        service_doc("svc", FINANCE),
        agent_doc("ops", OPERATIONS),
        service_doc("opssvc", OPERATIONS),
    )
    api.seed_edges(
        make_edge("fin-svc", agent_id("fin"), service_id("svc"), relation="depends_on"),
        make_edge(
            "ops-svc", agent_id("ops"), service_id("opssvc"), OPERATIONS, relation="depends_on"
        ),
    )
    return World(api=api, denials=denials)


def call(
    world: World,
    route: str,
    who: str | None,
    domain: str,
    node_id: str | None = None,
    **headers_extra: Any,
) -> Any:
    """Issue one request against ``route`` (one of ``ROUTES``) as ``who`` (``None``: no token)."""
    api = world.api
    headers = api.h.auth(who, **headers_extra) if who else {}
    client = api.h.client
    base = f"{PREFIX}/domains/{domain}"
    match route:
        case "viewport":
            return client.get(f"{base}/viewport", headers=headers)
        case "search":
            return client.get(f"{base}/search", headers=headers, params={"q": ""})
        case "neighborhood":
            assert node_id is not None
            return client.get(f"{base}/neighborhood/{quote(node_id, safe=':/')}", headers=headers)
        case "impact":
            assert node_id is not None
            return client.post(f"{base}/impact", headers=headers, json={"node_id": node_id})
    raise AssertionError(f"unknown route {route}")
