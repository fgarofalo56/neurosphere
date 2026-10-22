"""FinOps forecast (PRP-21 item 4): model, schema, side-by-side backtest, scope, evidence."""

import asyncio
import json
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from finops_support import (  # pyright: ignore[reportMissingImports]
    ALICE,
    BOB,
    CUSTOMER,
    FINANCE,
    MONTH_START,
    NOW,
    OPERATIONS,
    OTHER_CUSTOMER_FINANCE,
    VERSION,
    Spec,
    daily,
    make_api,
    make_store,
)
from neurosphere_api.finops import build_forecast
from neurosphere_api.finops.evidence import build_evidence, write_evidence
from neurosphere_api.finops.models import (
    Amount,
    EstimatedSeries,
    ForecastResponse,
    ForecastValue,
    InvoicedSeries,
    known_amount,
)
from neurosphere_api.finops.sandbox_source import load_sandbox_ledger
from pydantic import ValidationError

AS_OF = date(2026, 10, 11)
LINEAR = [str(10 + 2 * i) for i in range(10)]  # 10, 12, ... 28 on Oct 1..10
NOISY = ["10", "14", "9", "15", "11", "16", "12", "19", "13", "18"]
EVIDENCE_FILE = (
    Path(__file__).resolve().parents[4]
    / "docs"
    / "evidence"
    / "G07"
    / "finops"
    / "forecast-vs-actual-sandbox.json"
)


def _forecast(specs: list[Spec], **kwargs: Any) -> ForecastResponse:
    options: dict[str, Any] = {
        "customer_id": CUSTOMER,
        "domain_id": FINANCE,
        "as_of": AS_OF,
        "today": date(2026, 11, 1),
        "history_days": 10,
        "horizon_days": 5,
    }
    options.update(kwargs)
    return asyncio.run(build_forecast(make_store(specs), **options))


def _series_response(**overrides: Any) -> dict[str, Any]:
    base = _forecast(daily(MONTH_START, LINEAR)).model_dump(mode="python")
    base.update(overrides)
    return base


def test_linear_history_extrapolates_exactly_with_a_zero_width_band() -> None:
    response = _forecast(daily(MONTH_START, LINEAR))
    horizon = [p for p in response.estimated.points if p.phase == "horizon"]
    assert [p.forecast.value for p in horizon if p.forecast] == [
        Decimal(30),
        Decimal(32),
        Decimal(34),
        Decimal(36),
        Decimal(38),
    ]
    first = horizon[0].forecast
    assert first is not None
    assert first.lower == first.value == first.upper
    assert response.estimated.fit_points == 10


def test_noisy_history_gives_a_band_that_widens_with_distance() -> None:
    response = _forecast(daily(MONTH_START, NOISY))
    horizon = [p.forecast for p in response.estimated.points if p.phase == "horizon" and p.forecast]
    widths = [f.upper - f.lower for f in horizon]
    assert all(f.lower <= f.value <= f.upper for f in horizon)
    assert widths[0] > 0
    assert widths == sorted(widths)
    assert widths[-1] > widths[0]
    assert response.estimated.residual_std is not None
    assert response.estimated.residual_std > 0


def test_band_is_clamped_at_zero_for_a_falling_trend() -> None:
    response = _forecast(daily(MONTH_START, [str(20 - 2 * i) for i in range(10)]), horizon_days=8)
    forecasts = [p.forecast for p in response.estimated.points if p.forecast]
    assert forecasts
    assert all(f.lower >= 0 and f.value >= 0 for f in forecasts)
    assert forecasts[-1].value == 0


def test_response_cites_the_price_version_and_keeps_series_separate() -> None:
    specs = [
        Spec(day, estimated="10.00", invoiced="9.50") for day in [MONTH_START, date(2026, 10, 2)]
    ]
    specs += daily(date(2026, 10, 3), ["10", "11", "12", "13", "14", "15", "16", "17"])
    response = _forecast(specs)
    assert response.price_version_id == VERSION
    assert response.price_version_ids == [VERSION]
    assert response.estimated.kind == "estimated"
    assert response.invoiced.kind == "invoiced"
    dumped = response.model_dump(mode="json")
    assert set(dumped) == {
        "domain_id",
        "as_of",
        "method",
        "price_version_id",
        "price_version_ids",
        "estimated",
        "invoiced",
    }
    first_est = response.estimated.points[0].actual
    first_inv = response.invoiced.points[0].actual
    assert first_est.value == Decimal("10")
    assert first_inv.value == Decimal("9.5")  # never summed with, or replaced by, the estimate
    assert response.method.savings_claim is False


def test_backtest_reports_forecast_and_actual_side_by_side() -> None:
    specs = daily(MONTH_START, [*LINEAR, "30", "32", "34", "36", "38"])
    response = _forecast(specs)
    horizon = [p for p in response.estimated.points if p.phase == "horizon"]
    assert len(horizon) == 5
    for point in horizon:
        assert point.forecast is not None
        assert point.actual.status == "known"
        assert point.within_band is True
    assert response.estimated.summary.horizon_actual.value == Decimal(170)
    assert response.estimated.summary.horizon_forecast is not None
    assert response.estimated.summary.horizon_forecast.value == Decimal(170)


def test_missing_price_version_is_rejected_by_the_response_model() -> None:
    payload = _series_response()
    del payload["price_version_id"]
    with pytest.raises(ValidationError):
        ForecastResponse.model_validate(payload)
    with pytest.raises(ValidationError):
        ForecastResponse.model_validate(_series_response(price_version_id=""))
    with pytest.raises(ValidationError):
        ForecastResponse.model_validate(_series_response(price_version_id="not-cited"))


def test_mixing_estimated_with_invoiced_is_rejected_by_schema() -> None:
    payload = _series_response()
    swapped = {**payload, "estimated": {**payload["invoiced"], "kind": "invoiced"}}
    with pytest.raises(ValidationError):
        ForecastResponse.model_validate(swapped)
    with pytest.raises(ValidationError):
        ForecastResponse.model_validate({**payload, "invoiced": payload["estimated"]})
    with pytest.raises(ValidationError):
        EstimatedSeries.model_validate({**payload["estimated"], "kind": "invoiced"})
    with pytest.raises(ValidationError):
        InvoicedSeries.model_validate({**payload["invoiced"], "kind": "estimated"})
    with pytest.raises(ValidationError):  # no combined figure can be smuggled in
        ForecastResponse.model_validate({**payload, "total": "1.00"})


def test_money_rejects_floats_and_inverted_bands() -> None:
    with pytest.raises(ValidationError):
        Amount.model_validate({"value": 1.5, "status": "known", "complete": True})
    with pytest.raises(ValidationError):
        ForecastValue.model_validate({"value": "1", "lower": "2", "upper": "3"})
    assert known_amount(Decimal("1.5"), complete=True).value == Decimal("1.5")


def test_route_returns_the_forecast_for_a_domain_viewer() -> None:
    api = make_api(daily(MONTH_START, [*LINEAR, "30", "32", "34", "36", "38"]))
    response = api.get(ALICE, FINANCE, as_of=AS_OF.isoformat(), history_days=10, horizon_days=5)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["price_version_id"] == VERSION
    assert body["estimated"]["kind"] == "estimated"
    assert body["invoiced"]["kind"] == "invoiced"
    horizon = [p for p in body["estimated"]["points"] if p["phase"] == "horizon"]
    assert horizon[0]["forecast"]["value"] == "30.000000000000"
    assert horizon[0]["actual"]["value"] == "30.000000000000"


def test_route_denies_other_domains_unauthenticated_and_unknown_domains() -> None:
    api = make_api(daily(MONTH_START, LINEAR))
    assert api.get(ALICE, OPERATIONS).status_code == 403  # ALICE views FINANCE only
    assert api.get(BOB, FINANCE).status_code == 403
    assert api.get(None, FINANCE).status_code == 401
    ghost = "commercial:contoso:catalog:domain:ghost"
    assert api.get(ALICE, ghost).status_code == 403


def test_route_ignores_a_spoofed_customer_and_domain() -> None:
    mine = daily(MONTH_START, LINEAR)
    foreign = [
        Spec(s.day, estimated="9999.00", customer="fabrikam", domain=OTHER_CUSTOMER_FINANCE)
        for s in mine
    ]
    other_domain = [Spec(s.day, estimated="8888.00", domain=OPERATIONS) for s in mine]
    api = make_api(mine + foreign + other_domain)
    response = api.get(
        ALICE,
        FINANCE,
        as_of=AS_OF.isoformat(),
        history_days=10,
        horizon_days=5,
        customer_id="fabrikam",
        domain_id=OPERATIONS,
    )
    assert response.status_code == 200
    assert "9999" not in response.text
    assert "8888" not in response.text
    first = response.json()["estimated"]["points"][0]["actual"]["value"]
    assert Decimal(first) == Decimal(10)


def test_no_price_version_is_a_409_not_a_forecast() -> None:
    api = make_api([])
    response = api.get(ALICE, FINANCE)
    assert response.status_code == 409
    assert response.json()["code"] == "capability_unavailable"


def test_future_as_of_and_out_of_range_budgets_are_rejected() -> None:
    api = make_api(daily(MONTH_START, LINEAR))
    assert api.get(ALICE, FINANCE, as_of=NOW.date().isoformat()).status_code == 200
    assert api.get(ALICE, FINANCE, as_of="2026-12-01").status_code == 422
    assert api.get(ALICE, FINANCE, history_days=3).status_code == 422
    assert api.get(ALICE, FINANCE, horizon_days=400).status_code == 422
    assert api.get(ALICE, FINANCE, currency="usd").status_code == 422


def test_unconfigured_ledger_fails_closed_with_503() -> None:
    api = make_api([], configured=False)
    response = api.get(ALICE, FINANCE)
    assert response.status_code == 503


def test_sandbox_month_reports_forecast_and_actual_with_the_price_version() -> None:
    sandbox = asyncio.run(load_sandbox_ledger())
    response = asyncio.run(
        build_forecast(
            sandbox.store,
            customer_id=sandbox.customer_id,
            domain_id=sandbox.domain_ids[0],
            as_of=date(2026, 10, 18),
            today=date(2026, 11, 1),
            history_days=17,
            horizon_days=14,
        )
    )
    assert response.price_version_id == "sandbox-prices-2026-10"
    assert response.estimated.forecast_available
    horizon = [p for p in response.estimated.points if p.phase == "horizon"]
    assert len(horizon) == 14
    assert all(p.forecast is not None and p.actual.status == "known" for p in horizon)
    assert all(p.forecast.lower <= p.forecast.upper for p in horizon if p.forecast)
    invoiced_actuals = [p.actual for p in response.invoiced.points]
    assert any(a.status == "known" for a in invoiced_actuals)  # some invoices exist
    assert all(a.value is None for a in invoiced_actuals if a.status == "unknown")


def test_evidence_document_has_environment_method_date_version_and_no_savings_claim(
    tmp_path: Path,
) -> None:
    response = _forecast(daily(MONTH_START, [*LINEAR, "30", "32", "34", "36", "38"]))
    evidence = build_evidence(
        response,
        environment="sandbox in-memory ledger, synthetic data",
        generated_on=date(2026, 10, 22),
        currency="USD",
        data_description="unit test",
    )
    path = tmp_path / "out" / "evidence.json"
    write_evidence(path, evidence)
    loaded = json.loads(path.read_text(encoding="utf-8"))
    assert loaded["environment"] == "sandbox in-memory ledger, synthetic data"
    assert loaded["generated_on"] == "2026-10-22"
    assert loaded["price_version_id"] == VERSION
    assert loaded["method"]["name"] == "linear_trend_ols"
    assert loaded["savings_claim"] is False
    assert {r["kind"] for r in loaded["rows"]} == {"estimated", "invoiced"}
    assert len(loaded["rows"]) == 10  # 5 horizon days x 2 kinds, never summed


def test_committed_evidence_was_produced_by_the_hook() -> None:
    loaded = json.loads(EVIDENCE_FILE.read_text(encoding="utf-8"))
    assert loaded["environment"] == "sandbox in-memory ledger, synthetic data"
    assert loaded["price_version_id"] == "sandbox-prices-2026-10"
    assert loaded["savings_claim"] is False
    assert loaded["rows"]
    assert all(r["kind"] in {"estimated", "invoiced"} for r in loaded["rows"])
    assert "savings" not in json.dumps(loaded["rows"]).lower()
