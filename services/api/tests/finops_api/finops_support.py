"""Harness for the FinOps API tests: the PRP-06 authz harness (dev-issuer tokens, in-memory policy
store) with the real router, an in-memory cost ledger and a fixed clock. No network."""

import asyncio
import hashlib
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

import authz.authz_helpers as helpers  # pyright: ignore[reportMissingImports]
from neurosphere_api.finops import PREFIX, build_router, get_clock, get_ledger_store
from neurosphere_core.auth.scope import Role
from neurosphere_core.ledger import (
    DEFAULT_COST_CATEGORY,
    CostLedger,
    InMemoryLedgerStore,
    Observation,
)

ALICE: str = helpers.ALICE
BOB: str = helpers.BOB
CUSTOMER: str = helpers.CUSTOMER
FINANCE: str = helpers.FINANCE
OPERATIONS: str = helpers.OPERATIONS
OTHER_CUSTOMER_FINANCE: str = helpers.OTHER_CUSTOMER_FINANCE
NOW = datetime(2026, 11, 1, 12, 0, tzinfo=UTC)
MONTH_START = date(2026, 10, 1)
VERSION = "pv-2026-10"

_UNSET: Any = object()
_counter = {"n": 0}


def _doc_id() -> str:
    _counter["n"] += 1
    return hashlib.sha256(f"finops-test-{_counter['n']}".encode()).hexdigest()


def observation(
    day: date,
    *,
    kind: str = "estimated",
    amount: str | None = "1.00",
    currency: str | None = "USD",
    version: str | None = VERSION,
    domain: str = FINANCE,
) -> Observation:
    source = "billing" if kind == "invoiced" else "gateway"
    return Observation(
        observation_kind=source,  # type: ignore[arg-type]
        doc_id=_doc_id(),
        kind=kind,  # type: ignore[arg-type]
        amount=None if amount is None else Decimal(amount),
        currency=currency if amount is not None else None,
        price_version_id=version if kind == "estimated" else None,
        observed_at=datetime(day.year, day.month, day.day, 9, 0, tzinfo=UTC),
        cloud="commercial",
        source_id="test-source",
        domain_id=domain,
    )


@dataclass(frozen=True, slots=True)
class Spec:
    """One request's worth of cost on ``day``. ``estimated``/``invoiced``: a decimal string,
    ``None`` = unknown amount, ``_UNSET`` = no observation of that kind at all."""

    day: date
    estimated: Any = "1.00"
    invoiced: Any = _UNSET
    domain: str = FINANCE
    customer: str = CUSTOMER
    currency: str = "USD"


NO_OBSERVATION = _UNSET


async def _fill(store: InMemoryLedgerStore, specs: Sequence[Spec]) -> None:
    ledger = CostLedger(store)
    for index, spec in enumerate(specs):
        request = f"req-{index}"
        if spec.estimated is not _UNSET:
            await ledger.record(
                spec.customer,
                request,
                DEFAULT_COST_CATEGORY,
                observation(
                    spec.day, amount=spec.estimated, currency=spec.currency, domain=spec.domain
                ),
            )
        if spec.invoiced is not _UNSET:
            await ledger.record(
                spec.customer,
                request,
                DEFAULT_COST_CATEGORY,
                observation(
                    spec.day,
                    kind="invoiced",
                    amount=spec.invoiced,
                    currency=spec.currency,
                    domain=spec.domain,
                ),
            )


def make_store(specs: Sequence[Spec]) -> InMemoryLedgerStore:
    store = InMemoryLedgerStore()
    asyncio.run(_fill(store, specs))
    return store


def days(start: date, count: int) -> list[date]:
    return [start + timedelta(days=i) for i in range(count)]


def daily(start: date, amounts: Sequence[str | None], **kwargs: Any) -> list[Spec]:
    """One spec per day with the given estimated amount (``None`` = unknown)."""
    return [
        Spec(day, estimated=a, **kwargs)
        for day, a in zip(days(start, len(amounts)), amounts, strict=True)
    ]


@dataclass
class Api:
    h: Any
    store: InMemoryLedgerStore

    def get(self, who: str | None, domain: str, **params: Any) -> Any:
        headers = self.h.auth(who) if who else {}
        return self.h.client.get(
            f"{PREFIX}/domains/{domain}/forecast", params=params or None, headers=headers
        )


def make_api(specs: Sequence[Spec], *, configured: bool = True) -> Api:
    h = helpers.harness(
        helpers.policy(ALICE, helpers.role(Role.VIEWER, FINANCE)),
        helpers.policy(BOB, helpers.role(Role.VIEWER, OPERATIONS)),
        routers={PREFIX: build_router()},
    )
    store = make_store(specs)
    if configured:
        h.app.dependency_overrides[get_ledger_store] = lambda: store
    h.app.dependency_overrides[get_clock] = lambda: lambda: NOW
    return Api(h=h, store=store)
