"""World generator and API assembly for the live-map timing runs (PRP-74 item 5).

Pure data generation plus an app wired with the real map router over any ``CatalogRepository``.
No timing target is asserted anywhere in this package.

The documents come from the map test harness (``services/api/tests/map/map_api_helpers.py``),
put on ``sys.path`` here because those directories have no ``__init__.py``.
"""

import asyncio
import copy
import sys
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_API_TESTS = Path(__file__).resolve().parents[3] / "services" / "api" / "tests"
for _path in (_API_TESTS, _API_TESTS / "map"):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

import httpx  # noqa: E402
import map_api_helpers as mah  # noqa: E402  # pyright: ignore[reportMissingImports]
from authz.authz_helpers import (  # noqa: E402  # pyright: ignore[reportMissingImports]
    ALICE,
    harness,
    policy,
    pseudonymizer,
    role,
)
from neurosphere_api.map import build_router, get_clock  # noqa: E402
from neurosphere_core.aggregates import AggregateStatus, InMemoryAggregateStore  # noqa: E402
from neurosphere_core.auth.scope import Role  # noqa: E402
from neurosphere_core.catalog import CatalogRepository  # noqa: E402
from neurosphere_core.catalog.graph import RepositoryGraphQuery  # noqa: E402
from neurosphere_core.catalog.repo.documents import (  # noqa: E402
    parse_entity,
    revalidate_edge,
)
from neurosphere_core.catalog.repo.engine import new_etag  # noqa: E402
from neurosphere_core.scope import IdentityScope  # noqa: E402
from neurosphere_core.search.fixture import FixtureSearchIndex  # noqa: E402

PERF_DOMAIN = "commercial:contoso:catalog:domain:perf-prp74"
PREFIX = mah.PREFIX
ROOT_SERVICE = mah.service_id("imp-root")
# Impact tree: agents per level below the root service (depth 1..5), 5,120 dependents in all.
IMPACT_LEVELS = (20, 100, 500, 1500, 3000)
IMPACT_AGENTS = sum(IMPACT_LEVELS)

_cache: dict[str, dict[str, Any]] = {}


def _cached_example(name: str) -> dict[str, Any]:
    """Read each example file once (the stock helper re-reads it per document)."""
    if name not in _cache:
        _cache[name] = _original_example(name)
    return copy.deepcopy(_cache[name])


_original_example = mah.example
mah.example = _cached_example


def impact_agent(level: int, index: int) -> str:
    return mah.agent_id(f"imp{level}x{index:04d}")


def background_docs(count: int, domain: str = PERF_DOMAIN) -> list[dict[str, Any]]:
    """``count`` entities cycling agent, tool, service, model and MCP server, with facets."""
    docs: list[dict[str, Any]] = []
    for i in range(count):
        name = f"w{i:06d}"
        match i % 5:
            case 0:
                doc = mah.agent_doc(name, domain)
            case 1:
                doc = mah.tool_doc(name, domain)
            case 2:
                doc = mah.service_doc(name, domain)
            case 3:
                doc = mah.model_doc(name, domain)
            case _:
                doc = mah.mcp_doc(name, domain)
        doc.update(
            environment="production" if i % 4 == 0 else "staging",
            tags=["payments"] if i % 3 == 0 else ["internal"],
        )
        docs.append(doc)
    return docs


def impact_docs(domain: str = PERF_DOMAIN) -> list[dict[str, Any]]:
    docs = [mah.service_doc("imp-root", domain)]
    for level, width in enumerate(IMPACT_LEVELS, start=1):
        docs.extend(mah.agent_doc(f"imp{level}x{i:04d}", domain) for i in range(width))
    return docs


def impact_edges(domain: str = PERF_DOMAIN) -> list[Any]:
    """Level 1 depends on the root service; each deeper agent invokes one agent a level up."""
    edges: list[Any] = [
        mah.make_edge(
            f"imp1x{i:04d}-root", impact_agent(1, i), ROOT_SERVICE, domain, relation="depends_on"
        )
        for i in range(IMPACT_LEVELS[0])
    ]
    for level in range(2, len(IMPACT_LEVELS) + 1):
        parents = IMPACT_LEVELS[level - 2]
        for i in range(IMPACT_LEVELS[level - 1]):
            edges.append(
                mah.make_edge(
                    f"imp{level}x{i:04d}",
                    impact_agent(level, i),
                    impact_agent(level - 1, i % parents),
                    domain,
                )
            )
    return edges


def background_edges(count: int, domain: str = PERF_DOMAIN) -> list[Any]:
    """One ``depends_on`` per 10 background entities: an agent on the next service along."""
    edges: list[Any] = []
    for i in range(0, count - 3, 10):
        agent = i - i % 5  # an index that is an agent (i % 5 == 0)
        service = agent + 2
        if service >= count:
            continue
        edges.append(
            mah.make_edge(
                f"w{agent:06d}-w{service:06d}",
                mah.agent_id(f"w{agent:06d}"),
                mah.service_id(f"w{service:06d}"),
                domain,
                relation="depends_on",
            )
        )
    return edges


@dataclass
class PerfApi:
    """The map app over ``repo`` plus an in-process async HTTP client (one event loop)."""

    api: mah.Api
    reader: IdentityScope
    repo: CatalogRepository
    client: httpx.AsyncClient

    async def get(self, path: str, **params: Any) -> httpx.Response:
        return await self.client.get(
            f"{PREFIX}/domains/{PERF_DOMAIN}/{path}",
            headers=self.api.h.auth(ALICE),
            params=params,
        )

    async def post_impact(self, node_id: str, max_depth: int) -> httpx.Response:
        return await self.client.post(
            f"{PREFIX}/domains/{PERF_DOMAIN}/impact",
            headers=self.api.h.auth(ALICE),
            json={"node_id": node_id, "max_depth": max_depth},
        )


async def build_api(repo: CatalogRepository) -> PerfApi:
    """The real map router over ``repo`` for one viewer of the perf domain.

    Async on purpose: a Cosmos client binds to the event loop it first runs in, so seeding, the
    HTTP calls and the topology polls must all share the caller's loop (no ``TestClient``).
    """
    h = harness(
        policy(ALICE, role(Role.VIEWER, PERF_DOMAIN), memberships=(PERF_DOMAIN,)),
        routers={PREFIX: build_router()},
    )
    store = InMemoryAggregateStore()
    h.app.state.catalog_repository = repo
    h.app.state.aggregate_reader = store
    h.app.state.map_pseudonymizer = pseudonymizer()
    # The four map routes never use the graph's search index; an empty fixture index is wired
    # so no 50k-document index is built (the repository does the scanning).
    h.app.state.catalog_graph = RepositoryGraphQuery(repo, FixtureSearchIndex([]))
    h.app.dependency_overrides[get_clock] = lambda: lambda: mah.NOW
    status = AggregateStatus(customer_id=mah.CUSTOMER, watermark="2027-01-15T08:30:00Z")
    await store.put_status(status)
    api = mah.Api(h=h, repo=repo, store=store)  # type: ignore[arg-type]
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=h.app), base_url="http://perf")
    return PerfApi(api=api, reader=await api.scope_of(ALICE), repo=repo, client=client)


async def _bounded(jobs: list[Callable[[], Awaitable[Any]]], concurrency: int) -> None:
    gate = asyncio.Semaphore(concurrency)

    async def run(job: Callable[[], Awaitable[Any]]) -> None:
        async with gate:
            await job()

    await asyncio.gather(*(run(j) for j in jobs))


async def load_world(
    perf: PerfApi, docs: list[dict[str, Any]], edges: list[Any], *, concurrency: int = 1
) -> None:
    """Insert every entity then every edge (``concurrency`` writes in flight).

    Documents go straight to the repository's backend, skipping ``create_entity``'s per-write
    duplicate lookup (a full scan on the in-memory backend, a cross-partition query on Cosmos):
    the generated ids are unique by construction, so the lookup would only add seeding time.
    The stored shape is the one ``create_entity`` and ``put_edge`` write.
    """
    repo: Any = perf.repo
    entity_docs: list[dict[str, Any]] = []
    for raw in docs:
        body, domain = repo._entity_parts(parse_entity(raw))
        body["version"] = 1
        body["etag"] = new_etag()
        entity_docs.append(repo._entity_doc(body, domain))
    edge_docs: list[dict[str, Any]] = []
    for edge in edges:
        edge_body = revalidate_edge(edge)
        edge_body["version"] = 1
        edge_body["etag"] = new_etag()
        edge_docs.append(repo._edge_doc(edge_body))
    backend = repo._backend
    await _bounded([(lambda d=d: backend.insert(d)) for d in entity_docs], concurrency)  # type: ignore[misc]
    await _bounded([(lambda d=d: backend.insert(d)) for d in edge_docs], concurrency)  # type: ignore[misc]
