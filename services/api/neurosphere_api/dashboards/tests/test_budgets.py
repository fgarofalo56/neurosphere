"""Query budgets: 422 outside the bounds, ``truncated`` when cut, hour grain limited to 14 days and
a ``Server-Timing`` header on served responses."""

import re

import pytest

from neurosphere_api.dashboards.tests.support import ALICE, FINANCE, cost_point, make_api


@pytest.mark.parametrize(
    "params",
    [
        {"days": 0},
        {"days": 91},
        {"days": -3},
        {"grain": "week"},
        {"max_series": 0},
        {"max_series": 51},
        {"max_points": 0},
        {"max_points": 2161},
        {"days": "many"},
    ],
)
def test_out_of_range_budgets_are_422(params: dict[str, object]) -> None:
    api = make_api()
    response = api.get(ALICE, FINANCE, "cost", **params)
    assert response.status_code == 422, response.text


@pytest.mark.parametrize(
    "params",
    [
        {"days": 1},
        {"days": 90},
        {"max_series": 1},
        {"max_series": 50},
        {"max_points": 1},
        {"max_points": 2160},
        {"grain": "hour", "days": 14},
    ],
)
def test_boundary_budgets_are_accepted(params: dict[str, object]) -> None:
    api = make_api()
    assert api.get(ALICE, FINANCE, "cost", **params).status_code == 200


def test_hour_grain_above_14_days_is_rejected() -> None:
    api = make_api()
    response = api.get(ALICE, FINANCE, "cost", grain="hour", days=15)
    assert response.status_code == 422
    assert response.json()["reason"] == "hour_window"


def test_unknown_metric_is_422() -> None:
    api = make_api()
    assert api.get(ALICE, FINANCE, "revenue").status_code == 422


def test_points_beyond_max_points_set_truncated() -> None:
    api = make_api()
    api.seed(*(cost_point(FINANCE, i, "1.00") for i in range(6)))
    response = api.get(ALICE, FINANCE, "cost", days=30, max_points=3)
    body = response.json()
    assert body["truncated"] is True
    assert len(body["series"][0]["points"]) == 3
    assert body["series"][0]["total"]["complete"] is False  # older points were cut
    assert body["complete"] is False

    whole = api.get(ALICE, FINANCE, "cost", days=30, max_points=10).json()
    assert whole["truncated"] is False
    assert len(whole["series"][0]["points"]) == 6


def test_series_beyond_max_series_set_truncated() -> None:
    api = make_api()
    api.seed(
        cost_point(FINANCE, 1, "1", kind="estimated"),
        cost_point(FINANCE, 1, "1", kind="invoiced"),
        cost_point(FINANCE, 1, "1", kind="estimated", currency="EUR"),
    )
    body = api.get(ALICE, FINANCE, "cost", max_series=2).json()
    assert body["truncated"] is True
    assert len(body["series"]) == 2


def test_window_matches_days_and_grain() -> None:
    api = make_api()
    body = api.get(ALICE, FINANCE, "cost", days=7).json()
    assert body["grain"] == "day"
    assert body["window"] == {"start": "2027-01-09T00:00:00Z", "end": "2027-01-16T00:00:00Z"}
    hourly = api.get(ALICE, FINANCE, "cost", days=1, grain="hour").json()
    assert hourly["window"] == {"start": "2027-01-14T09:00:00Z", "end": "2027-01-15T09:00:00Z"}


def test_server_timing_header_on_every_served_metric() -> None:
    api = make_api()
    for metric in ("cost", "latency", "errors", "coverage"):
        response = api.get(ALICE, FINANCE, metric)
        assert response.status_code == 200
        assert re.fullmatch(r"app;dur=\d+(\.\d+)?", response.headers["Server-Timing"]), (
            response.headers.get("Server-Timing")
        )
