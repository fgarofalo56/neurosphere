"""CosmosRecommendationStore on the emulator: the shared conformance checks."""

from __future__ import annotations

import pytest
from azure.cosmos.aio import DatabaseProxy
from neurosphere_core.recommendations.cosmos_store import (
    DEFAULT_RECOMMENDATION_CONTAINER,
    CosmosRecommendationStore,
    create_recommendation_container,
)

from .support import load_conformance

pytestmark = pytest.mark.integration

conformance = load_conformance("recommendations_cosmos")


@pytest.mark.parametrize("check", sorted(conformance.CHECKS))
async def test_conformance_on_the_emulator(database: DatabaseProxy, check: str) -> None:
    container = await create_recommendation_container(database)
    assert container.id == DEFAULT_RECOMMENDATION_CONTAINER
    await conformance.CHECKS[check](CosmosRecommendationStore(container))
