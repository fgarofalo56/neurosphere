"""Unknown is never 0 in the FinOps forecast (PRP-21 item 4; ledger semantics: ``None`` = unknown).

An unknown contribution never silently lowers a figure: the day/summary becomes
``complete: false`` (sum of the known parts) or ``unknown`` with ``value: null``.
"""

import asyncio
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

import pytest
from finops_support import (  # pyright: ignore[reportMissingImports]
    ALICE,
    CUSTOMER,
    FINANCE,
    MONTH_START,
    NO_OBSERVATION,
    Spec,
    daily,
    make_api,
    make_store,
)
from neurosphere_api.finops import build_forecast
from neurosphere_api.finops.models import Amount, ForecastResponse
from neurosphere_api.finops.service import MIN_FIT_POINTS, day_totals
from neurosphere_core.ledger import TimeWindow
from pydantic import ValidationError

AS_OF = date(2026, 10, 11)
TODAY = date(2026, 11, 1)
FULL = [str(10 + 2 * i) for i in range(10)]


def _forecast(specs: list[Spec], **kwargs: Any) -> ForecastResponse:
    options: dict[str, Any] = {
        "customer_id": CUSTOMER,
        "domain_id": FINANCE,
        "as_of": AS_OF,
        "today": TODAY,
        "history_days": 10,
        "horizon_days": 5,
    }
    options.update(kwargs)
    return asyncio.run(build_forecast(make_store(specs), **options))


def _entries(specs: list[Spec]) -> list[Any]:
    window = TimeWindow(datetime(2026, 9, 1, tzinfo=UTC), datetime(2026, 12, 1, tzinfo=UTC))
    return asyncio.run(make_store(specs).list_entries(CUSTOMER, window))


def test_a_day_with_no_entries_is_unknown_not_zero() -> None:
    totals = day_totals([], "estimated", "USD", [MONTH_START])
    amount = totals[MONTH_START]
    assert amount.status == "unknown"
    assert amount.value is None
    assert amount.complete is False


def test_a_day_with_only_unknown_amounts_is_unknown_not_zero() -> None:
    entries = _entries([Spec(MONTH_START, estimated=None), Spec(MONTH_START, estimated=None)])
    amount = day_totals(entries, "estimated", "USD", [MONTH_START])[MONTH_START]
    assert amount.status == "unknown"
    assert amount.value is None
    assert amount.reason == "all_amounts_unknown"


def test_a_partly_unknown_day_is_the_known_sum_flagged_incomplete() -> None:
    entries = _entries([Spec(MONTH_START, estimated="5.00"), Spec(MONTH_START, estimated=None)])
    amount = day_totals(entries, "estimated", "USD", [MONTH_START])[MONTH_START]
    assert amount.status == "known"
    assert amount.value == Decimal(5)
    assert amount.complete is False  # never presented as the complete day
    assert amount.reason == "some_amounts_unknown"


def test_a_genuine_zero_stays_a_complete_known_zero() -> None:
    entries = _entries([Spec(MONTH_START, estimated="0.00")])
    amount = day_totals(entries, "estimated", "USD", [MONTH_START])[MONTH_START]
    assert amount.status == "known"
    assert amount.value == Decimal(0)
    assert amount.complete is True


def test_a_day_without_invoices_is_unknown_for_invoiced_not_zero() -> None:
    entries = _entries([Spec(MONTH_START, estimated="5.00", invoiced=NO_OBSERVATION)])
    est = day_totals(entries, "estimated", "USD", [MONTH_START])[MONTH_START]
    inv = day_totals(entries, "invoiced", "USD", [MONTH_START])[MONTH_START]
    assert est.value == Decimal(5)
    assert inv.status == "unknown"
    assert inv.value is None
    assert inv.reason == "no_invoiced_observations"


def test_an_entry_in_another_currency_is_an_unknown_contribution() -> None:
    entries = _entries(
        [Spec(MONTH_START, estimated="5.00"), Spec(MONTH_START, estimated="7.00", currency="EUR")]
    )
    amount = day_totals(entries, "estimated", "USD", [MONTH_START])[MONTH_START]
    assert amount.value == Decimal(5)  # EUR is not added into USD
    assert amount.complete is False


def test_incomplete_days_are_excluded_from_the_fit_and_counted() -> None:
    amounts: list[str | None] = [*FULL]
    amounts[3] = None  # one unknown day among ten
    response = _forecast(daily(MONTH_START, amounts))
    assert response.estimated.fit_points == 9
    assert response.estimated.excluded_incomplete_days == 1
    history = [p for p in response.estimated.points if p.phase == "history"]
    assert history[3].actual.status == "unknown"
    assert history[3].actual.value is None
    # The line is fitted on x positions that skip the gap: the unknown day is not 0 in the fit.
    first = next(p.forecast for p in response.estimated.points if p.forecast)
    assert first.value == Decimal(30)
    assert response.estimated.summary.history_actual.complete is False


def test_too_few_complete_days_makes_the_forecast_unavailable_not_zero() -> None:
    amounts: list[str | None] = [None] * (10 - (MIN_FIT_POINTS - 1)) + FULL[: MIN_FIT_POINTS - 1]
    response = _forecast(daily(MONTH_START, amounts))
    assert response.estimated.forecast_available is False
    assert response.estimated.forecast_unavailable_reason is not None
    assert response.estimated.residual_std is None
    assert response.estimated.summary.horizon_forecast is None
    assert all(p.forecast is None for p in response.estimated.points)


def test_invoiced_forecast_is_unavailable_when_there_are_no_invoices() -> None:
    response = _forecast(daily(MONTH_START, FULL))
    assert response.invoiced.forecast_available is False
    assert response.invoiced.fit_points == 0
    assert all(p.actual.value is None for p in response.invoiced.points)
    assert all(p.actual.status == "unknown" for p in response.invoiced.points)
    assert response.invoiced.summary.history_actual.status == "unknown"
    assert response.invoiced.summary.history_actual.value is None


def test_days_not_yet_observed_are_unknown() -> None:
    response = _forecast(daily(MONTH_START, FULL), today=AS_OF)  # "today" is the first forecast day
    horizon = [p for p in response.estimated.points if p.phase == "horizon"]
    assert all(p.actual.status == "unknown" for p in horizon)
    assert all(p.actual.value is None and p.actual.reason == "not_yet_observed" for p in horizon)
    assert all(p.within_band is None for p in horizon)
    assert response.estimated.summary.horizon_actual.value is None


def test_a_partly_unknown_horizon_total_is_flagged_incomplete() -> None:
    specs = daily(MONTH_START, [*FULL, "30", None, "34", "36", "38"])
    response = _forecast(specs)
    summary = response.estimated.summary.horizon_actual
    assert summary.status == "known"
    assert summary.value == Decimal(138)  # known parts only ...
    assert summary.complete is False  # ... and never presented as the whole
    assert summary.reason == "incomplete_days"


def test_route_serializes_unknown_as_null_not_zero() -> None:
    api = make_api(daily(MONTH_START, FULL))
    response = api.get(ALICE, FINANCE, as_of=AS_OF.isoformat(), history_days=10, horizon_days=5)
    assert response.status_code == 200
    invoiced = response.json()["invoiced"]
    first = invoiced["points"][0]["actual"]
    assert first["value"] is None
    assert first["status"] == "unknown"
    assert first["complete"] is False
    assert invoiced["forecast_available"] is False
    assert invoiced["summary"]["horizon_forecast"] is None


@pytest.mark.parametrize(
    "payload",
    [
        {"value": None, "status": "known", "complete": True},
        {"value": "0", "status": "unknown", "complete": False},
        {"value": None, "status": "unknown", "complete": True},
    ],
)
def test_amount_schema_pairs_unknown_with_null_only(payload: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        Amount.model_validate(payload)
