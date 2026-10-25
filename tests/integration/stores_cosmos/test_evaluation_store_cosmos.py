"""CosmosEvaluationStore on the emulator: the shared conformance checks."""

from __future__ import annotations

import pytest
from azure.cosmos.aio import DatabaseProxy
from neurosphere_core.evaluation.cosmos_store import (
    DEFAULT_RESULTS_CONTAINER,
    DEFAULT_RUNS_CONTAINER,
    CosmosEvaluationStore,
    create_evaluation_containers,
)

from .support import load_conformance

pytestmark = pytest.mark.integration

conformance = load_conformance("evaluation_cosmos")


@pytest.mark.parametrize("check", sorted(conformance.CHECKS))
async def test_conformance_on_the_emulator(database: DatabaseProxy, check: str) -> None:
    results, runs = await create_evaluation_containers(database)
    assert (results.id, runs.id) == (DEFAULT_RESULTS_CONTAINER, DEFAULT_RUNS_CONTAINER)
    await conformance.CHECKS[check](CosmosEvaluationStore(results, runs))
