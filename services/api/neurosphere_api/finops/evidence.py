"""Evidence hook: forecast-versus-actual rows for ``docs/evidence/G07/finops/`` (PRP-21 item 4).

:func:`build_evidence` turns a :class:`ForecastResponse` into a flat, reviewable document: one row
per kind (estimated / invoiced, never combined) and horizon day with the forecast, its band, the
actual, and whether the actual fell inside the band. Every document names its environment, method,
date and price version, and states that it makes no savings claim. Unknown stays ``null``
(``actual_status: "unknown"``), never 0.
"""

import json
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any, Final

from neurosphere_api.finops.models import Amount, ForecastResponse, ForecastValue, SeriesPoint

__all__ = ["EVIDENCE_SCHEMA_VERSION", "build_evidence", "write_evidence"]

EVIDENCE_SCHEMA_VERSION: Final = "1"
NO_SAVINGS_CLAIM: Final = (
    "Forecast versus actual cost only. This is not a savings estimate, a recommendation or a "
    "claim that any cost would be avoided."
)


def _money(value: Decimal | None) -> str | None:
    return None if value is None else format(value, "f")


def _row(kind: str, point: SeriesPoint) -> dict[str, Any]:
    forecast: ForecastValue | None = point.forecast
    actual: Amount = point.actual
    return {
        "kind": kind,
        "day": point.day.isoformat(),
        "forecast": _money(forecast.value) if forecast else None,
        "band_lower": _money(forecast.lower) if forecast else None,
        "band_upper": _money(forecast.upper) if forecast else None,
        "actual": _money(actual.value),
        "actual_status": actual.status,
        "actual_complete": actual.complete,
        "actual_reason": actual.reason,
        "within_band": point.within_band,
    }


def build_evidence(
    response: ForecastResponse,
    *,
    environment: str,
    generated_on: date,
    currency: str,
    data_description: str,
) -> dict[str, Any]:
    rows = [
        _row(series.kind, point)
        for series in (response.estimated, response.invoiced)
        for point in series.points
        if point.phase == "horizon"
    ]
    return {
        "schema_version": EVIDENCE_SCHEMA_VERSION,
        "gate": "G07",
        "item": "PRP-21 item 4 finops-forecast",
        "environment": environment,
        "data": data_description,
        "generated_on": generated_on.isoformat(),
        "domain_id": response.domain_id,
        "as_of": response.as_of.isoformat(),
        "currency": currency,
        "price_version_id": response.price_version_id,
        "price_version_ids": response.price_version_ids,
        "method": response.method.model_dump(mode="json"),
        "series": {
            series.kind: {
                "forecast_available": series.forecast_available,
                "forecast_unavailable_reason": series.forecast_unavailable_reason,
                "fit_points": series.fit_points,
                "excluded_incomplete_days": series.excluded_incomplete_days,
                "residual_std": _money(series.residual_std),
                "history_actual": series.summary.history_actual.model_dump(mode="json"),
                "horizon_actual": series.summary.horizon_actual.model_dump(mode="json"),
                "horizon_forecast": (
                    series.summary.horizon_forecast.model_dump(mode="json")
                    if series.summary.horizon_forecast
                    else None
                ),
            }
            for series in (response.estimated, response.invoiced)
        },
        "rows": rows,
        "savings_claim": False,
        "note": NO_SAVINGS_CLAIM,
    }


def write_evidence(path: Path, evidence: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(evidence, indent=2, sort_keys=True, ensure_ascii=False)
    path.write_text(text + "\n", encoding="utf-8", newline="\n")
