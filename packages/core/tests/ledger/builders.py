"""Synthetic builders for the ledger tests. The price tables are NOT real list prices."""

from __future__ import annotations

import hashlib
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from neurosphere_core.ledger import (
    ModelRate,
    Observation,
    PriceTable,
    PriceVersion,
    Rate,
    TimeWindow,
)

CUSTOMER = "cust-1"
REQUEST = "req-1"
CATEGORY = "model_inference"
T0 = datetime(2026, 10, 1, 12, 0, 0, tzinfo=UTC)
WINDOW = TimeWindow(datetime(2026, 1, 1, tzinfo=UTC), datetime(2027, 1, 1, tzinfo=UTC))


def doc_id(n: int | str) -> str:
    return hashlib.sha256(f"doc-{n}".encode()).hexdigest()


def D(value: str) -> Decimal:  # noqa: N802 - terse test helper
    return Decimal(value)


def obs(
    n: int | str,
    *,
    source: str = "gateway",
    kind: str = "estimated",
    amount: str | None = "1.00",
    currency: str | None = "USD",
    version: str | None = "pv-1",
    unresolved: bool = False,
    at: datetime = T0,
    period_end: date | None = None,
    **extra: object,
) -> Observation:
    fields: dict[str, object] = {"provider": "prov-a", "model": "model-x", **extra}
    return Observation(
        observation_kind=source,  # type: ignore[arg-type]
        doc_id=doc_id(n),
        kind=kind,  # type: ignore[arg-type]
        amount=None if amount is None else Decimal(amount),
        currency=currency if amount is not None else None,
        price_version_id=None if unresolved else version,
        price_unresolved=unresolved,
        observed_at=at,
        period_end=period_end,
        cloud="commercial",
        source_id="src-1",
        **fields,  # type: ignore[arg-type]
    )


def gateway(n: int | str, amount: str | None = "1.00", **kw: Any) -> Observation:
    return obs(n, source="gateway", amount=amount, **kw)


def application(n: int | str, amount: str | None = "0.90", **kw: Any) -> Observation:
    return obs(n, source="application", amount=amount, **kw)


def billing(n: int | str, amount: str | None = "1.20", **kw: Any) -> Observation:
    kw.setdefault("version", None)
    kw.setdefault("period_end", date(2026, 10, 31))
    return obs(n, source="billing", kind="invoiced", amount=amount, **kw)


def price_table() -> PriceTable:
    rates_v1 = [
        ModelRate(
            provider="prov-a",
            model="model-x",
            rate=Rate(input=D("2.00"), output=D("8.00"), cached=D("0.50")),
        ),
        ModelRate(
            provider="prov-a",
            model="model-y",
            model_version="2",
            rate=Rate(input=D("1.00"), output=D("4.00")),
        ),
    ]
    rates_v2 = [
        ModelRate(
            provider="prov-a",
            model="model-x",
            rate=Rate(input=D("3.00"), output=D("9.00"), cached=D("0.75")),
        )
    ]
    return PriceTable(
        [
            PriceVersion(
                price_version_id="pv-2026-01",
                effective_date=date(2026, 1, 1),
                currency="USD",
                source="synthetic-sheet-a",
                rates=rates_v1,
            ),
            PriceVersion(
                price_version_id="pv-2026-09",
                effective_date=date(2026, 9, 1),
                currency="USD",
                source="synthetic-sheet-b",
                rates=rates_v2,
            ),
        ]
    )
