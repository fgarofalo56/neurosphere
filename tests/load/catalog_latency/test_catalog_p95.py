"""Catalog read latency over the sandbox dataset (PRP-10 items 5 and 13): MEASURED, never asserted.

What this is: wall-clock p50/p95/max of scoped catalog reads (entity get, filtered list, scoped
export page, search, neighbors, impact paths) against the IN-MEMORY repository loaded from the
``sandbox/`` generator (custom profile: 8 domains, 200 agents), through the same
``CatalogRepository``, ``CatalogService.export_page`` and ``GraphQuery`` the API uses. The
in-memory backend scans documents (no index), so the numbers say nothing about Cosmos NoSQL or
Azure AI Search.

What this is not: a performance claim. The PRP-10 target (p95 <= 500 ms on indexed scoped
queries) is only evidenced by the live gate against a real account (G03). This test records the
numbers so a regression in the query layer is visible, prints them, and writes
``temp/catalog_latency/p95.json`` (gitignored) labelled "in-memory, bounded feasibility, not a
live claim". It asserts correctness (every result is inside the caller's scope) and that the
measurement was recorded, not any latency threshold.

The Cosmos emulator and live backends are in ``test_catalog_p95_cosmos.py``. Size knob for a
bigger local run: ``NS_CATALOG_LATENCY_ITERATIONS`` (default 60).
"""

from __future__ import annotations

import asyncio
from typing import Any

from neurosphere_core.catalog.repo import InMemoryCatalogRepository

from .harness import RESULT_DIR, check_and_record, make_world, measure

LABEL = "in-memory, bounded feasibility, not a live claim"
RESULT_PATH = RESULT_DIR / "p95.json"


async def _measure() -> dict[str, Any]:
    world, all_domains, agents = make_world()
    return await measure(
        InMemoryCatalogRepository(),
        world,
        all_domains,
        agents,
        label=LABEL,
        disclaimer=(
            "Measured against the in-memory repository (no index, no network). This is not "
            "evidence for the PRP-10 p95 target; the live gate G03 is still required."
        ),
    )


def test_scoped_read_latency_is_measured_and_recorded() -> None:
    check_and_record(asyncio.run(_measure()), LABEL, RESULT_PATH)
