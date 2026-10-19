"""Pure mapping from aggregate documents (item 1) to the wire contract's series.

Null semantics (NS-01): ``None`` in a document is unknown and maps to ``{"value": null,
"status": "unknown"}``, never 0. A total over partly unknown points is the sum of the KNOWN points
with ``complete: false``; a total with no known point is unknown. A total over a truncated result
is also incomplete because older points were cut. Estimated and invoiced cost are separate series
per currency and are never blended.

Latency percentiles cannot be combined across buckets, so a latency series total is unknown rather
than an invented number.
"""

from collections.abc import Iterable
from decimal import Decimal

from neurosphere_core.aggregates import (
    CostPoint,
    CoveragePoint,
    ErrorPoint,
    LatencyPoint,
    PriceVersionRef,
    QueryResult,
)
from neurosphere_core.ledger.models import UNKNOWN_CURRENCY

from neurosphere_api.dashboards.models import (
    UNKNOWN,
    MetricName,
    MetricValue,
    Point,
    PriceVersion,
    Series,
    SeriesKind,
    SeriesUnit,
    known_value,
)

__all__ = ["MappedMetric", "map_result"]


class MappedMetric:
    """Series plus the price versions seen, in a stable order."""

    __slots__ = ("price_versions", "series")

    def __init__(self, series: list[Series], price_versions: list[PriceVersion]) -> None:
        self.series = series
        self.price_versions = price_versions


def _currency(code: str) -> str | None:
    return None if code == UNKNOWN_CURRENCY else code


def _resolved(refs: Iterable[PriceVersionRef]) -> tuple[list[PriceVersion], bool]:
    """Price versions with a known effective date, and whether every ref resolved."""
    found: dict[str, PriceVersion] = {}
    all_resolved = True
    for ref in refs:
        if ref.effective_date is None:
            all_resolved = False
            continue
        found[ref.id] = PriceVersion(id=ref.id, effective_date=ref.effective_date)
    return sorted(found.values(), key=lambda p: (p.effective_date, p.id)), all_resolved


def _latest(versions: list[PriceVersion]) -> PriceVersion | None:
    return versions[-1] if versions else None  # sorted by effective date, newest last


def _wrap(
    key: str,
    label: str,
    kind: SeriesKind | None,
    unit: SeriesUnit,
    currency: str | None,
    total: MetricValue,
    points: list[Point],
) -> Series:
    return Series(
        key=key, label=label, kind=kind, unit=unit, currency=currency, total=total, points=points
    )


# --------------------------------------------------------------------------- cost


def _cost_series(
    key: str, points: tuple[CostPoint, ...], truncated: bool
) -> tuple[Series, list[PriceVersion]]:
    first = points[0]
    seen: list[PriceVersion] = []
    mapped: list[Point] = []
    known_sum = Decimal(0)
    any_known = False
    all_complete = not truncated
    for point in points:
        versions, resolved = _resolved(point.price_versions)
        seen.extend(versions)
        if point.amount is None:
            value = UNKNOWN
            all_complete = False
        else:
            complete = point.complete and resolved
            value = known_value(point.amount, complete=complete, price_version=_latest(versions))
            known_sum += point.amount
            any_known = True
            all_complete = all_complete and complete
        mapped.append(Point(t=point.bucket_start, value=value))
    if any_known:
        total = known_value(
            known_sum,
            complete=all_complete,
            price_version=_latest(_resolved_union(seen)),
        )
    else:
        total = UNKNOWN
    label = f"{first.kind.capitalize()} cost ({first.currency})"
    series = _wrap(key, label, first.kind, "currency", _currency(first.currency), total, mapped)
    return series, seen


def _resolved_union(versions: list[PriceVersion]) -> list[PriceVersion]:
    unique = {v.id: v for v in versions}
    return sorted(unique.values(), key=lambda p: (p.effective_date, p.id))


# --------------------------------------------------------------------------- latency


def _latency_series(points: tuple[LatencyPoint, ...]) -> list[Series]:
    out: list[Series] = []
    for name in ("p50", "p95", "p99"):
        mapped: list[Point] = []
        for point in points:
            raw: int | None = getattr(point, f"{name}_ms")
            value = (
                UNKNOWN
                if raw is None
                else known_value(raw, complete=point.complete and point.missing_count == 0)
            )
            mapped.append(Point(t=point.bucket_start, value=value))
        out.append(_wrap(name, f"Latency {name} (ms)", None, "ms", None, UNKNOWN, mapped))
    return out


# --------------------------------------------------------------------------- errors


def _error_series(points: tuple[ErrorPoint, ...], truncated: bool) -> list[Series]:
    rate_points: list[Point] = []
    count_points: list[Point] = []
    errors = 0
    requests = 0
    any_count = False
    all_complete = not truncated
    for point in points:
        complete = point.complete and point.unknown_count == 0
        if point.error_rate is None:
            rate_points.append(Point(t=point.bucket_start, value=UNKNOWN))
        else:
            rate_points.append(
                Point(t=point.bucket_start, value=known_value(point.error_rate, complete=complete))
            )
        if point.error_count is None:
            count_points.append(Point(t=point.bucket_start, value=UNKNOWN))
            all_complete = False
        else:
            count_points.append(
                Point(t=point.bucket_start, value=known_value(point.error_count, complete=complete))
            )
            errors += point.error_count
            requests += point.request_count
            any_count = True
            all_complete = all_complete and complete
    count_total = known_value(errors, complete=all_complete) if any_count else UNKNOWN
    rate_total = known_value(errors / requests, complete=all_complete) if requests > 0 else UNKNOWN
    return [
        _wrap("error_rate", "Error rate", None, "ratio", None, rate_total, rate_points),
        _wrap("error_count", "Error count", None, "count", None, count_total, count_points),
    ]


# --------------------------------------------------------------------------- coverage


def _coverage_series(key: str, points: tuple[CoveragePoint, ...], truncated: bool) -> Series:
    first = points[0]
    mapped: list[Point] = []
    known = 0
    entries = 0
    all_complete = not truncated
    for point in points:
        if point.coverage is None:
            mapped.append(Point(t=point.bucket_start, value=UNKNOWN))
            all_complete = False
        else:
            mapped.append(
                Point(
                    t=point.bucket_start,
                    value=known_value(point.coverage, complete=point.complete),
                )
            )
            all_complete = all_complete and point.complete
        known += point.known_count
        entries += point.entry_count
    total = known_value(known / entries, complete=all_complete) if entries > 0 else UNKNOWN
    return _wrap(
        f"coverage:{first.currency}",
        f"Coverage ({first.currency})",
        None,
        "ratio",
        _currency(first.currency),
        total,
        mapped,
    )


# --------------------------------------------------------------------------- entry point


def map_result(metric: MetricName, result: QueryResult) -> MappedMetric:
    series: list[Series] = []
    versions: list[PriceVersion] = []
    for aggregate in result.series:
        if not aggregate.points:
            continue
        if metric == "cost":
            cost = tuple(p for p in aggregate.points if isinstance(p, CostPoint))
            if cost:
                one, seen = _cost_series(aggregate.key, cost, result.truncated)
                series.append(one)
                versions.extend(seen)
        elif metric == "latency":
            lat = tuple(p for p in aggregate.points if isinstance(p, LatencyPoint))
            if lat:
                series.extend(_latency_series(lat))
        elif metric == "errors":
            err = tuple(p for p in aggregate.points if isinstance(p, ErrorPoint))
            if err:
                series.extend(_error_series(err, result.truncated))
        else:
            cov = tuple(p for p in aggregate.points if isinstance(p, CoveragePoint))
            if cov:
                series.append(_coverage_series(aggregate.key, cov, result.truncated))
    return MappedMetric(series, _resolved_union(versions))
