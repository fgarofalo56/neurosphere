"""Forecast computation over ledger entries (PRP-21 item 4). Pure functions plus one async entry
point; the router and the evidence hook both call :func:`build_forecast`.

Model (simple and explainable, no ML): per kind (estimated / invoiced separately), take the
daily totals of the history window that are COMPLETE (every contributing entry has a known amount
in the requested currency), fit an ordinary-least-squares line ``y = a + b * x`` (x = day index),
and extrapolate over the horizon. The band is the normal-approximation prediction interval
``y_hat +/- z * s * sqrt(1 + 1/n + (x - x_mean)^2 / Sxx)`` with ``z = 1.96`` (about 95 %) and ``s``
the residual standard deviation (``n - 2`` degrees of freedom). It is clamped at 0 from below. The
band widens away from the data, and it widens with noisy history. It is an approximation (small
samples would need a t quantile); it is not a guarantee and not a savings claim.

Unknown handling: an incomplete day is excluded from the fit (a partial sum would bias the line
low) and counted in ``excluded_incomplete_days``; a day with no contributing entries or only
unknown amounts is ``unknown`` (``value: null``), never 0; fewer than ``MIN_FIT_POINTS`` complete
days means the forecast is unavailable (explicitly), not a number.

All money arithmetic is ``Decimal``.
"""

from collections.abc import Callable, Iterable
from datetime import UTC, date, datetime, timedelta
from decimal import Context, Decimal, localcontext
from typing import Final

from neurosphere_core.errors import CapabilityUnavailableError
from neurosphere_core.ledger import LedgerEntry, LedgerStore, TimeWindow

from neurosphere_api.finops.models import (
    Amount,
    EstimatedSeries,
    ForecastMethod,
    ForecastResponse,
    ForecastValue,
    InvoicedSeries,
    SeriesPoint,
    SeriesSummary,
    known_amount,
    unknown_amount,
)

__all__ = [
    "MIN_FIT_POINTS",
    "Z_95",
    "build_forecast",
    "day_totals",
    "fit_and_predict",
]

MIN_FIT_POINTS: Final = 5
Z_95: Final = Decimal("1.96")
_ZERO: Final = Decimal(0)
_CTX: Final = Context(prec=40)

Kind = str


def _day(entry: LedgerEntry) -> date:
    return entry.occurred_at.astimezone(UTC).date()


def _contributes(entry: LedgerEntry, kind: Kind) -> bool:
    return any(o.kind == kind for o in entry.observations)


def _amount_of(entry: LedgerEntry, kind: Kind, currency: str) -> Decimal | None:
    """The entry's amount of ``kind`` in ``currency``; ``None`` is unknown (never 0)."""
    if kind == "estimated":
        amount, cur = entry.estimated_amount, entry.estimated_currency
    else:
        amount, cur = entry.invoiced_amount, entry.invoiced_currency
    if amount is None or cur != currency:
        return None
    return amount


def day_totals(
    entries: Iterable[LedgerEntry], kind: Kind, currency: str, days: Iterable[date]
) -> dict[date, Amount]:
    """One :class:`Amount` per requested day for one kind. Never mixes kinds."""
    by_day: dict[date, list[LedgerEntry]] = {}
    for entry in entries:
        by_day.setdefault(_day(entry), []).append(entry)
    result: dict[date, Amount] = {}
    for day in days:
        todays = by_day.get(day, [])
        if not todays:
            result[day] = unknown_amount("no_observations")
            continue
        contributing = [e for e in todays if _contributes(e, kind)]
        if not contributing:
            result[day] = unknown_amount(f"no_{kind}_observations")
            continue
        amounts = [_amount_of(e, kind, currency) for e in contributing]
        known = [a for a in amounts if a is not None]
        if not known:
            result[day] = unknown_amount("all_amounts_unknown")
        elif len(known) < len(amounts):
            result[day] = known_amount(
                sum(known, _ZERO), complete=False, reason="some_amounts_unknown"
            )
        else:
            result[day] = known_amount(sum(known, _ZERO), complete=True)
    return result


def fit_and_predict(
    history: list[tuple[int, Decimal]], horizon_x: list[int]
) -> tuple[list[ForecastValue], Decimal] | None:
    """OLS fit over ``(x, y)`` points and prediction at ``horizon_x``; ``None`` if too few
    points. Returns the forecasts and the residual standard deviation."""
    n = len(history)
    if n < MIN_FIT_POINTS:
        return None
    with localcontext(_CTX):
        count = Decimal(n)
        x_mean = sum((Decimal(x) for x, _ in history), _ZERO) / count
        y_mean = sum((y for _, y in history), _ZERO) / count
        sxx = sum(((Decimal(x) - x_mean) ** 2 for x, _ in history), _ZERO)
        if sxx == 0:
            return None
        sxy = sum(((Decimal(x) - x_mean) * (y - y_mean) for x, y in history), _ZERO)
        slope = sxy / sxx
        intercept = y_mean - slope * x_mean
        sse = sum(((y - (intercept + slope * Decimal(x))) ** 2 for x, y in history), _ZERO)
        s = (sse / Decimal(n - 2)).sqrt()
        out: list[ForecastValue] = []
        for x in horizon_x:
            point = intercept + slope * Decimal(x)
            spread = Z_95 * s * (1 + 1 / count + (Decimal(x) - x_mean) ** 2 / sxx).sqrt()
            out.append(
                ForecastValue(
                    value=max(point, _ZERO),
                    lower=max(point - spread, _ZERO),
                    upper=max(point + spread, _ZERO),
                )
            )
        return out, s


def _sum_amounts(amounts: list[Amount]) -> Amount:
    known = [a.value for a in amounts if a.value is not None]
    if not amounts or not known:
        return unknown_amount("no_known_days")
    complete = all(a.status == "known" and a.complete for a in amounts)
    return known_amount(
        sum(known, _ZERO), complete=complete, reason=None if complete else "incomplete_days"
    )


def _sum_forecasts(values: list[ForecastValue]) -> ForecastValue | None:
    if not values:
        return None
    return ForecastValue(
        value=sum((v.value for v in values), _ZERO),
        lower=sum((v.lower for v in values), _ZERO),
        upper=sum((v.upper for v in values), _ZERO),
    )


def _series_fields(
    kind: Kind,
    entries: list[LedgerEntry],
    currency: str,
    history_days: list[date],
    horizon_days: list[date],
    observed_through: date,
) -> dict[str, object]:
    actual = day_totals(entries, kind, currency, [*history_days, *horizon_days])
    fit: list[tuple[int, Decimal]] = []
    excluded = 0
    for index, day in enumerate(history_days):
        amount = actual[day]
        if amount.status == "known" and amount.complete and amount.value is not None:
            fit.append((index, amount.value))
        else:
            excluded += 1
    horizon_x = [len(history_days) + i for i in range(len(horizon_days))]
    fitted = fit_and_predict(fit, horizon_x)
    forecasts = fitted[0] if fitted is not None else []
    reason = (
        None
        if fitted is not None
        else f"fewer than {MIN_FIT_POINTS} complete history days for {kind} cost"
    )
    points: list[SeriesPoint] = []
    for day in history_days:
        points.append(SeriesPoint(day=day, phase="history", actual=actual[day]))
    for i, day in enumerate(horizon_days):
        observed = actual[day] if day < observed_through else unknown_amount("not_yet_observed")
        forecast = forecasts[i] if forecasts else None
        within = (
            forecast.lower <= observed.value <= forecast.upper
            if forecast is not None and observed.status == "known" and observed.value is not None
            else None
        )
        points.append(
            SeriesPoint(
                day=day, phase="horizon", actual=observed, forecast=forecast, within_band=within
            )
        )
    summary = SeriesSummary(
        history_actual=_sum_amounts([actual[d] for d in history_days]),
        horizon_actual=_sum_amounts([p.actual for p in points if p.phase == "horizon"]),
        horizon_forecast=_sum_forecasts(forecasts),
    )
    return {
        "currency": currency,
        "points": points,
        "summary": summary,
        "forecast_available": fitted is not None,
        "forecast_unavailable_reason": reason,
        "fit_points": len(fit),
        "excluded_incomplete_days": excluded,
        "residual_std": fitted[1] if fitted is not None else None,
    }


def _price_versions(entries: list[LedgerEntry]) -> tuple[str, list[str]] | None:
    """(latest cited version id, all cited ids) over the estimated observations, or ``None``."""
    cited: list[tuple[datetime, str]] = []
    for entry in entries:
        for obs in entry.observations:
            if obs.kind == "estimated" and obs.price_version_id is not None:
                cited.append((obs.observed_at, obs.price_version_id))
    if not cited:
        return None
    latest = max(cited)[1]
    return latest, sorted({version for _, version in cited})


async def build_forecast(
    store: LedgerStore,
    *,
    customer_id: str,
    domain_id: str,
    as_of: date,
    today: date,
    history_days: int,
    horizon_days: int,
    currency: str = "USD",
    entry_filter: Callable[[LedgerEntry], bool] | None = None,
) -> ForecastResponse:
    """Forecast ``horizon_days`` from ``as_of`` using the ``history_days`` before it.

    ``customer_id`` and ``domain_id`` must come from the server-derived scope / authorized path.
    Raises ``CapabilityUnavailableError`` (409 ``price_version_unresolved``) when no estimated
    observation cites a price version: such a forecast would be rejected by the response model.
    """
    history = [as_of - timedelta(days=history_days - i) for i in range(history_days)]
    horizon = [as_of + timedelta(days=i) for i in range(horizon_days)]
    window = TimeWindow(
        datetime.combine(history[0], datetime.min.time(), tzinfo=UTC),
        datetime.combine(horizon[-1] + timedelta(days=1), datetime.min.time(), tzinfo=UTC),
    )
    listed = await store.list_entries(customer_id, window)
    entries = [
        e
        for e in listed
        if e.customer_id == customer_id
        and e.domain_id == domain_id
        and window.contains(e.occurred_at)
        and (entry_filter is None or entry_filter(e))
    ]
    versions = _price_versions(entries)
    if versions is None:
        raise CapabilityUnavailableError(
            "price_version_unresolved",
            "no estimated cost observation cites a price version, so no forecast can be made",
        )
    return ForecastResponse(
        domain_id=domain_id,
        as_of=as_of,
        method=ForecastMethod(
            description=(
                "Ordinary least squares line over complete daily totals; band is the normal "
                "approximation prediction interval (z=1.96) clamped at 0. Not a savings claim."
            ),
            confidence_level="0.95",
            z=str(Z_95),
            min_fit_points=MIN_FIT_POINTS,
            history_days=history_days,
            horizon_days=horizon_days,
        ),
        price_version_id=versions[0],
        price_version_ids=versions[1],
        estimated=EstimatedSeries.model_validate(
            _series_fields("estimated", entries, currency, history, horizon, today)
        ),
        invoiced=InvoicedSeries.model_validate(
            _series_fields("invoiced", entries, currency, history, horizon, today)
        ),
    )
