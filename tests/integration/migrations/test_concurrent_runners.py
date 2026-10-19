"""Concurrent runners on the Cosmos emulator: the loser gets stale_version, no double apply.

G12: asserts document shape and versions only, not index behaviour or RU cost.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import pytest
from neurosphere_core.errors import StaleVersionError
from neurosphere_core.migrations import MigrationResult

if TYPE_CHECKING:
    from .support import Env

pytestmark = pytest.mark.integration


async def test_exactly_one_runner_applies(env: Env) -> None:
    outcomes = await asyncio.gather(
        env.runner("a").migrate(), env.runner("b").migrate(), return_exceptions=True
    )
    winners = [o for o in outcomes if isinstance(o, MigrationResult) and not o.noop]
    losers = [o for o in outcomes if isinstance(o, StaleVersionError)]
    assert len(winners) == 1
    assert (
        len(winners)
        + len(losers)
        + sum(isinstance(o, MigrationResult) and o.noop for o in outcomes)
        == 2
    )
    assert winners[0].documents_written == 16  # each step applied once per document
    docs = await env.documents()
    assert all(d["schema_version"] == 2 and "legacy_label" not in d for d in docs)
