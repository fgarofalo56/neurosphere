"""Load a month of synthetic cost records (``sandbox.costs``) into the in-memory cost ledger.

Used by the evidence hook and the tests. The data is synthetic; nothing here reads production
data. ``sandbox`` is the repo-level generator package, so this module needs the repository root on
``sys.path`` (true for ``python -m`` from the root and for pytest) and imports it lazily.
"""

import hashlib
import json
import sys
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Final

from neurosphere_core.ledger import (
    DEFAULT_COST_CATEGORY,
    CostLedger,
    InMemoryLedgerStore,
    Observation,
)

__all__ = ["SandboxLedger", "load_sandbox_ledger", "observation_from_cost_doc"]

_REPO_ROOT: Final = Path(__file__).resolve().parents[4]
SEED: Final = 7
AGENTS: Final = 24
DOMAINS: Final = 2
DAYS: Final = 31  # October 2026: one calendar month from the default sandbox epoch
TRACES_PER_AGENT_DAY: Final = 3.0
INVOICED_FRACTION: Final = 0.3


@dataclass(frozen=True, slots=True)
class SandboxLedger:
    store: InMemoryLedgerStore
    customer_id: str
    domain_ids: tuple[str, ...]
    record_count: int
    seed: int


def _parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)


def observation_from_cost_doc(doc: dict[str, Any]) -> tuple[str, Observation]:
    """(request_id, observation) for one sandbox ``CostRecord`` document.

    The ``dedupe_key`` shared by the gateway, application and billing views is the request id, so
    the ledger folds the three views of one call into one entry (no double count).
    """
    kind = doc["kind"]
    observation = Observation(
        observation_kind=doc["observation_source"],
        doc_id=hashlib.sha256(doc["cost_id"].encode("utf-8")).hexdigest(),
        kind=kind,
        amount=Decimal(doc["amount"]),
        currency=doc["currency"],
        price_version_id=doc.get("price_version") if kind == "estimated" else None,
        observed_at=_parse_time(doc["usage_end"]),
        cloud=doc["cloud"],
        source_id=doc["source_id"],
        domain_id=doc.get("domain_id"),
        provider=doc.get("provider"),
        model=doc.get("model"),
        model_version=doc.get("model_version"),
    )
    return doc["dedupe_key"], observation


async def load_sandbox_ledger(seed: int = SEED) -> SandboxLedger:
    """Generate a deterministic month of sandbox costs and fold them into a fresh ledger."""
    root = str(_REPO_ROOT)
    if root not in sys.path:
        sys.path.insert(0, root)  # the generator lives at the repository root, not in a package
    from sandbox.config import PROFILES, BadEventRates, GenerateConfig, with_overrides
    from sandbox.generate import generate

    profile = with_overrides(
        PROFILES["custom"],
        agents=AGENTS,
        domains=DOMAINS,
        days=DAYS,
        traces_per_agent_day=TRACES_PER_AGENT_DAY,
        invoiced_fraction=INVOICED_FRACTION,
    )
    cfg = GenerateConfig(seed=seed, profile=profile, cloud="commercial", rates=BadEventRates())
    store = InMemoryLedgerStore()
    ledger = CostLedger(store)
    domains: set[str] = set()
    count = 0
    with tempfile.TemporaryDirectory(prefix="ns-finops-sandbox-") as tmp:
        generate(cfg, Path(tmp))
        with (Path(tmp) / "cost.ndjson").open(encoding="utf-8") as handle:
            for line in handle:
                doc = json.loads(line)
                request_id, observation = observation_from_cost_doc(doc)
                await ledger.record(cfg.customer, request_id, DEFAULT_COST_CATEGORY, observation)
                if observation.domain_id is not None:
                    domains.add(observation.domain_id)
                count += 1
    return SandboxLedger(
        store=store,
        customer_id=cfg.customer,
        domain_ids=tuple(sorted(domains)),
        record_count=count,
        seed=seed,
    )
