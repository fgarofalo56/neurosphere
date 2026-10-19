"""Builders for the rules tests (synthetic data only, no network)."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from functools import cache
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator
from neurosphere_contracts.scope.v1.identity_scope import IdentityScope as ContractScope
from neurosphere_core.scope import IdentityScope

from neurosphere_workers.recommendations.rules import AgentDay, AgentSeries

REPO_ROOT = Path(__file__).resolve().parents[6]
SCHEMA_PATH = REPO_ROOT / "packages/contracts/schemas/recommendations/v1/recommendation.schema.json"
CREATED_AT = datetime(2026, 10, 19, 12, 0, 0, tzinfo=UTC)
CLOUD = "commercial"
CUSTOMER = "synthco"
DOMAIN = f"{CLOUD}:{CUSTOMER}:sandbox:domain:dom-001"


def make_scope(
    domains: tuple[str, ...] = (DOMAIN,), cloud: str = CLOUD, customer: str = CUSTOMER
) -> IdentityScope:
    contract = ContractScope.model_validate(
        {
            "schema_version": "1.0.0",
            "cloud": cloud,
            "customer_id": customer,
            "principal": {
                "principal_id": f"{cloud}:{customer}:entra:person:psn_0123456789abcdef",
                "principal_pseudonym": "p-7f3a9c21",
                "principal_kind": "user",
            },
            "roles": [],
            "allowed_domains": list(domains),
            "allowed_resources": [],
            "policy_version": "v1",
            "derived_at": "2026-10-10T00:00:00Z",
            "scope_hash": "sha256:" + hashlib.sha256(b"scope").hexdigest(),
        }
    )
    return IdentityScope._from_verified_contract(contract)  # pyright: ignore[reportPrivateUsage]


@cache
def _schema_validator() -> Draft202012Validator:
    return Draft202012Validator(json.loads(SCHEMA_PATH.read_text(encoding="utf-8")))


@cache
def _contract_validators() -> Any:
    contracts_dir = REPO_ROOT / "tests" / "contracts"
    if str(contracts_dir) not in sys.path:
        sys.path.append(str(contracts_dir))  # validators.py imports its sibling contract_support
    path = contracts_dir / "validators.py"
    spec = importlib.util.spec_from_file_location("ns_contract_validators", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def contract_problems(doc: dict[str, Any]) -> list[str]:
    """JSON Schema errors plus the extra cross-field validators named in the schema."""
    problems = [e.message for e in _schema_validator().iter_errors(doc)]
    v = _contract_validators()
    for check in (
        v.check_time_range_order,
        v.check_recommendation_score_interval,
        v.check_recommendation_same_boundary,
    ):
        problems += list(check(doc))
    return problems


class ListSource:
    """In-memory ``AgentSeriesSource`` over constructed series."""

    def __init__(self, *series: AgentSeries) -> None:
        self._series = series

    def series(
        self,
        *,
        cloud: str,
        customer_id: str,
        domain_ids: frozenset[str],
        start: date,
        end: date,
    ) -> list[AgentSeries]:
        return [
            s
            for s in self._series
            if s.cloud == cloud and s.customer_id == customer_id and s.domain_id in domain_ids
        ]


START = date(2026, 10, 1)


def day(offset: int, **kw: Any) -> AgentDay:
    kw.setdefault("covered", True)
    return AgentDay(day=START + timedelta(days=offset), **kw)


def agent(
    name: str = "a-1",
    days: tuple[AgentDay, ...] = (),
    *,
    source: str = "sandbox",
    status: str = "active",
    created_on: date | None = None,
    owner_id: str | None = None,
    domain: str = DOMAIN,
) -> AgentSeries:
    return AgentSeries(
        agent_id=f"{CLOUD}:{CUSTOMER}:{source}:agent:{name}",
        cloud=CLOUD,
        customer_id=CUSTOMER,
        domain_id=domain,
        source=source,
        lifecycle_status=status,
        created_on=created_on,
        owner_id=owner_id,
        days=days,
    )


def flat_days(
    n: int = 7,
    *,
    events: int = 10,
    requests: int = 10,
    errors: int = 0,
    p95: float | None = 100.0,
    p50: float | None = 50.0,
    cost: str | None = "1.00",
    patch: dict[int, dict[str, Any]] | None = None,
) -> tuple[AgentDay, ...]:
    """``n`` covered days with constant values; ``patch`` maps day offset to field overrides."""
    patch = patch or {}
    out = []
    for i in range(n):
        values: dict[str, Any] = {
            "event_count": events,
            "request_count": requests,
            "error_count": errors,
            "latency_p95_ms": p95,
            "latency_p50_ms": p50,
            "cost_amount": None if cost is None else Decimal(cost),
        }
        values.update(patch.get(i, {}))
        out.append(day(i, **values))
    return tuple(out)


END = START + timedelta(days=7)
