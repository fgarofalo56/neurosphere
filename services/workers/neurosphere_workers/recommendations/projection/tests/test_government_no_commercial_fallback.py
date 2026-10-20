"""Government projections need a snapshot that applies to Government; Commercial is no fallback."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from neurosphere_core.errors import InvalidSchemaError
from neurosphere_core.ledger.models import TokenCounts
from neurosphere_core.pricing import FIXTURE_DIR, InMemoryPriceSnapshotStore, load_snapshot_file
from neurosphere_workers.recommendations.projection import (
    CandidatePair,
    CandidatePairConfig,
    UsageSummary,
    project_right_sizing,
)

CREATED = datetime(2026, 10, 20, 8, 0, tzinfo=UTC)
PAIR = CandidatePair(
    pair_id="large-to-mini",
    provider="azure_openai",
    current_model="gpt-4.1",
    candidate_model="gpt-4.1-mini",
    candidate_model_version="2025-04-14",
)
CONFIG = CandidatePairConfig(config_id="pairs", version="1", pairs=(PAIR,))


def gov_usage() -> UsageSummary:
    return UsageSummary(
        agent_id="government:agency:foundry:agent:case-bot",
        cloud="government",
        customer_id="agency",
        domain_id="government:agency:catalog:domain:cases",
        provider="azure_openai",
        current_model="gpt-4.1",
        current_model_version="2025-04-14",
        tokens=TokenCounts(input=1_000_000, output=100_000),
        window_start=datetime(2026, 10, 1, tzinfo=UTC),
        window_end=datetime(2026, 10, 10, tzinfo=UTC),
        observed_fraction=1.0,
        coverage_method="full",
    )


def test_commercial_only_store_gives_no_government_projection() -> None:
    store = InMemoryPriceSnapshotStore(
        [load_snapshot_file(FIXTURE_DIR / "retail-prices-synthetic-2026-10.json")]
    )
    with pytest.raises(InvalidSchemaError) as caught:
        project_right_sizing(gov_usage(), PAIR, CONFIG, store, created_at=CREATED)
    assert caught.value.reason == "price_unresolved"


def test_government_sheet_projects_with_its_own_version() -> None:
    store = InMemoryPriceSnapshotStore(
        [
            load_snapshot_file(FIXTURE_DIR / "retail-prices-synthetic-2026-10.json"),
            load_snapshot_file(FIXTURE_DIR / "provider-sheet-gov-synthetic-2026-10.json"),
        ]
    )
    record = project_right_sizing(gov_usage(), PAIR, CONFIG, store, created_at=CREATED)
    assert record is not None and record.projected_estimate is not None
    assert record.cloud == "government"
    assert record.projected_estimate.price_version.root == "synthetic-gov-sheet-2026-10"
    # Priced from the Government sheet (x1.2 synthetic uplift): 1M*2.4 + 0.1M*9.6 = 3.36
    assert record.projected_estimate.baseline_amount.root == "3.360000000000"


def test_commercial_usage_never_uses_the_government_sheet() -> None:
    store = InMemoryPriceSnapshotStore(
        [load_snapshot_file(FIXTURE_DIR / "provider-sheet-gov-synthetic-2026-10.json")]
    )
    usage = gov_usage().model_copy(
        update={
            "cloud": "commercial",
            "customer_id": "agency",
            "agent_id": "commercial:agency:foundry:agent:case-bot",
            "domain_id": "commercial:agency:catalog:domain:cases",
        }
    )
    with pytest.raises(InvalidSchemaError):
        project_right_sizing(usage, PAIR, CONFIG, store, created_at=CREATED)
