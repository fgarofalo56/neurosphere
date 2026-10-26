"""CosmosPriceSnapshotStore on the emulator (sync client): the shared conformance checks."""

from __future__ import annotations

import pytest
from azure.cosmos import DatabaseProxy
from neurosphere_core.pricing.cosmos_store import (
    DEFAULT_PRICE_SNAPSHOT_CONTAINER,
    CosmosPriceSnapshotStore,
    create_price_snapshot_container,
)

from .support import load_conformance

pytestmark = pytest.mark.integration

conformance = load_conformance("pricing_cosmos")


@pytest.mark.parametrize("check", sorted(conformance.CHECKS))
def test_conformance_on_the_emulator(sync_database: DatabaseProxy, check: str) -> None:
    container = create_price_snapshot_container(sync_database)
    assert container.id == DEFAULT_PRICE_SNAPSHOT_CONTAINER
    conformance.CHECKS[check](CosmosPriceSnapshotStore(container))
