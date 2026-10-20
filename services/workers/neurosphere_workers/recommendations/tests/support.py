"""Test support for the pipeline: sandbox generation, scopes and a SYNTHETIC price snapshot.

Everything here is synthetic. The price snapshot is built from the sandbox price sheet
``sandbox-prices-2026-10`` (invented numbers, see ``sandbox/config.py``), never from a real
provider sheet. No network, no wall clock for data (fixed seed, epoch and ``CREATED_AT``).
"""

from __future__ import annotations

import hashlib
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from neurosphere_contracts.scope.v1.identity_scope import IdentityScope as ContractScope
from neurosphere_core.pricing import (
    InMemoryPriceSnapshotStore,
    PriceRow,
    TokenMeter,
    build_snapshot,
)
from neurosphere_core.scope import IdentityScope

from neurosphere_workers.recommendations.projection import CandidatePair, CandidatePairConfig
from sandbox.config import CACHED_INPUT_FACTOR, MODELS, BadEventRates, GenerateConfig, Profile
from sandbox.generate import generate

CREATED_AT = datetime(2026, 10, 19, 12, 0, 0, tzinfo=UTC)
SNAPSHOT_ID = "sandbox-prices-2026-10"
PAIRS = CandidatePairConfig(
    config_id="sandbox-pairs",
    version="2026.10.1",
    pairs=(
        CandidatePair(
            pair_id="large-to-mini",
            provider="azure_openai",
            current_model="gpt-4.1",
            candidate_model="gpt-4.1-mini",
            candidate_model_version="2025-04-14",
        ),
        CandidatePair(
            pair_id="mini-to-nano",
            provider="azure_openai",
            current_model="gpt-4.1-mini",
            candidate_model="gpt-4.1-nano",
            candidate_model_version="2025-04-14",
        ),
    ),
)


def pilot_profile(duplicate_pairs: int = 1) -> Profile:
    """Small but dense: 7 days (baseline plus recent), about 20 traces per agent per day, 3 of
    each injected anomaly and ``duplicate_pairs`` duplicate pairs (1 = the rules suite profile)."""
    return Profile(
        "custom",
        domains=4,
        agents=40,
        days=7,
        traces_per_agent_day=20.0,
        cost_spikes=3,
        latency_regressions=3,
        unused_agents=3,
        duplicate_pairs=duplicate_pairs,
    )


def generate_sandbox(
    out: Path, *, seed: int, customer: str = "synthco", profile: Profile | None = None
) -> None:
    config = GenerateConfig(
        seed=seed,
        profile=profile or pilot_profile(),
        cloud="commercial",
        customer=customer,
        rates=BadEventRates(),
    )
    generate(config, out)


def synthetic_sandbox_snapshot(*, models: tuple[str, ...] | None = None) -> Any:
    """SYNTHETIC snapshot of the sandbox price sheet (``sandbox-prices-2026-10``, USD per 1K
    tokens, cached input at the sandbox cached factor). ``models`` limits the covered models."""
    rows: list[PriceRow] = []
    for spec in MODELS:
        if models is not None and spec.model_name not in models:
            continue
        for kind, price in (
            ("input", spec.price_in),
            ("output", spec.price_out),
            ("cached", spec.price_in * CACHED_INPUT_FACTOR),
        ):
            rows.append(
                PriceRow(
                    service_name="SYNTHETIC sandbox price sheet",
                    sku_name=f"{spec.model_name} {kind}",
                    meter_name=f"SYNTHETIC {spec.model_name} {kind} tokens",
                    unit_of_measure="1K",
                    retail_price=price,
                    token_meter=TokenMeter(
                        provider=spec.provider,
                        model=spec.model_name,
                        model_version=spec.model_version,
                        kind=kind,  # type: ignore[arg-type]
                    ),
                )
            )
    return build_snapshot(
        snapshot_id=SNAPSHOT_ID,
        source="provider_price_sheet",
        source_url="https://pricing.invalid/sandbox-price-sheet",
        retrieval_date=date(2026, 10, 19),
        effective_date=date(2026, 10, 1),
        currency="USD",
        clouds=("commercial",),
        synthetic=True,
        notes="SYNTHETIC: the sandbox price sheet sandbox-prices-2026-10; invented numbers.",
        rows=rows,
    )


def synthetic_prices(*, models: tuple[str, ...] | None = None) -> InMemoryPriceSnapshotStore:
    return InMemoryPriceSnapshotStore([synthetic_sandbox_snapshot(models=models)])


def make_scope(
    domains: list[str], *, customer: str = "synthco", cloud: str = "commercial"
) -> IdentityScope:
    payload: dict[str, Any] = {
        "schema_version": "1.0.0",
        "cloud": cloud,
        "customer_id": customer,
        "principal": {
            "principal_id": f"{cloud}:{customer}:idp:person:p1",
            "principal_pseudonym": "p-0001",
            "principal_kind": "user",
        },
        "roles": [{"role": "viewer", "domain_ids": domains}],
        "allowed_domains": domains,
        "allowed_resources": [],
        "policy_version": "v1",
        "derived_at": "2026-01-01T00:00:00Z",
        "scope_hash": "sha256:" + hashlib.sha256(b"x").hexdigest(),
    }
    return IdentityScope._from_verified_contract(  # pyright: ignore[reportPrivateUsage]
        ContractScope.model_validate(payload)
    )
