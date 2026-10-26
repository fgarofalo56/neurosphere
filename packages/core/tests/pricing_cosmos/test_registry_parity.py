"""The price snapshot container constants equal the PRP-29 container registry entry."""

from __future__ import annotations

from neurosphere_core.pricing.cosmos_store import (
    DEFAULT_PRICE_SNAPSHOT_CONTAINER,
    PRICE_SNAPSHOT_PARTITION_KEY_PATH,
)
from neurosphere_core.stores.containers import container_spec


def test_price_snapshots_matches_the_registry() -> None:
    spec = container_spec(DEFAULT_PRICE_SNAPSHOT_CONTAINER)
    assert spec.partition_key_paths == (PRICE_SNAPSHOT_PARTITION_KEY_PATH,)
    assert spec.kind == "Hash"
