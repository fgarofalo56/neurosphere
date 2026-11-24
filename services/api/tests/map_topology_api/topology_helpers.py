"""Shared helpers for the PRP-74 item 2 tests (filters, search, neighbourhood).

Builds on ``services/api/tests/map/map_api_helpers.py`` (made importable by ``conftest.py``).
"""

import asyncio
from typing import Any
from urllib.parse import quote

from map_api_helpers import (  # pyright: ignore[reportMissingImports]
    FINANCE,
    PREFIX,
    STEWARD_BOTH,
    Api,
    agent_doc,
    mcp_doc,
    model_doc,
    service_doc,
    tool_doc,
)
from neurosphere_core.catalog.repo.documents import parse_entity

__all__ = [
    "bulk_seed",
    "get_neighborhood",
    "get_search",
    "mixed_world",
]


def bulk_seed(api: Api, docs: list[dict[str, Any]]) -> None:
    """Create many entities without rebuilding the graph search index per call."""

    async def run() -> None:
        scope = await api.scope_of(STEWARD_BOTH)
        for doc in docs:
            await api.repo.create_entity(scope, parse_entity(doc))

    asyncio.run(run())


def get_search(api: Api, who: str | None, domain: str, **params: Any) -> Any:
    headers = api.h.auth(who) if who else {}
    return api.h.client.get(f"{PREFIX}/domains/{domain}/search", headers=headers, params=params)


def get_neighborhood(api: Api, who: str | None, domain: str, node_id: str, **params: Any) -> Any:
    headers = api.h.auth(who) if who else {}
    return api.h.client.get(
        f"{PREFIX}/domains/{domain}/neighborhood/{quote(node_id, safe=':/')}",
        headers=headers,
        params=params,
    )


def mixed_world(total: int, domain: str = FINANCE) -> list[dict[str, Any]]:
    """``total`` entities cycling agent, tool, service, model and MCP server, with facets.

    Every 4th entity is ``production`` (the rest ``staging``) and every 3rd carries the tag
    ``payments`` (the rest ``internal``). Models carry no tags or environment field here.
    """
    docs: list[dict[str, Any]] = []
    for i in range(total):
        name = f"w{i:05d}"
        match i % 5:
            case 0:
                doc = agent_doc(name, domain)
            case 1:
                doc = tool_doc(name, domain)
            case 2:
                doc = service_doc(name, domain)
            case 3:
                doc = model_doc(name, domain)
            case _:
                doc = mcp_doc(name, domain)
        doc.update(
            environment="production" if i % 4 == 0 else "staging",
            tags=["payments"] if i % 3 == 0 else ["internal"],
        )
        docs.append(doc)
    return docs
