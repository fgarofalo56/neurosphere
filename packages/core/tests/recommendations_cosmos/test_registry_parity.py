"""The recommendation container constants equal the PRP-29 container registry entry."""

from __future__ import annotations

from neurosphere_core.recommendations.cosmos_store import (
    DEFAULT_RECOMMENDATION_CONTAINER,
    RECOMMENDATION_PARTITION_KEY_PATHS,
)
from neurosphere_core.stores.containers import container_spec


def test_recommendations_matches_the_registry() -> None:
    spec = container_spec(DEFAULT_RECOMMENDATION_CONTAINER)
    assert spec.partition_key_paths == tuple(RECOMMENDATION_PARTITION_KEY_PATHS)
    assert spec.kind == "MultiHash"
