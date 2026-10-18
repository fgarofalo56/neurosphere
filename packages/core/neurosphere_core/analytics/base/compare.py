"""Equivalence tolerance as code (PRP-11 clarification 3), shared by every adapter test.

Adapters are equivalent at the contract level, not identical internally. For identical
normalized input, two ``AggregateResult`` values are equivalent when:

* structure matches (metric, aggregation, group_by, time bucket) and the same groups exist;
* ``row_count`` and ``unknown_count`` are EXACTLY equal;
* ``count``, ``sum``, ``min`` and ``max`` values are EXACTLY equal (``Decimal`` compare, so
  money never goes through floats); unknown (``None``) equals only unknown;
* ``approx_quantile`` values agree within ``QUANTILE_REL_TOL`` relative error, with an absolute
  floor of ``QUANTILE_ABS_TOL`` for integer metrics (tokens, milliseconds) where a one-unit
  step is the engine resolution. Real engines (t-digest, KLL) are approximate; the
  2 percent bound is deliberate and documented, not a measurement. It does not prove identical
  SQL, plans or performance, and the live gate (Item 6) records the real delta (G12).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Final

from neurosphere_core.analytics.base.models import (
    INTEGER_METRICS,
    AggregateResult,
    AggregateRow,
    Aggregation,
)

QUANTILE_REL_TOL: Final = Decimal("0.02")
QUANTILE_ABS_TOL: Final = Decimal("1")


@dataclass(frozen=True)
class Mismatch:
    where: str  # "structure", or the group, e.g. "keys=('a',) bucket=None"
    field: str
    left: object
    right: object


def values_equivalent(
    left: Decimal | None, right: Decimal | None, *, approximate: bool, integer_metric: bool
) -> bool:
    if left is None or right is None:
        return left is None and right is None
    if not approximate:
        return left == right
    allowed = QUANTILE_REL_TOL * max(abs(left), abs(right))
    if integer_metric:
        allowed = max(allowed, QUANTILE_ABS_TOL)
    return abs(left - right) <= allowed


def _key(row: AggregateRow) -> tuple[tuple[str | None, ...], datetime | None]:
    return row.keys, row.bucket


def compare_results(left: AggregateResult, right: AggregateResult) -> list[Mismatch]:
    """Empty list = equivalent within the documented tolerance."""
    out: list[Mismatch] = []
    for name in ("metric", "aggregation", "quantile", "group_by", "time_bucket", "cloud"):
        a, b = getattr(left, name), getattr(right, name)
        if a != b:
            out.append(Mismatch("structure", name, a, b))
    if out:
        return out
    lrows = {_key(r): r for r in left.rows}
    rrows = {_key(r): r for r in right.rows}
    for key in sorted(lrows.keys() ^ rrows.keys(), key=repr):
        out.append(
            Mismatch(
                f"keys={key[0]} bucket={key[1]}",
                "presence",
                key in lrows,
                key in rrows,
            )
        )
    approximate = left.aggregation is Aggregation.APPROX_QUANTILE
    integer_metric = left.metric in INTEGER_METRICS
    for key in sorted(lrows.keys() & rrows.keys(), key=repr):
        a, b = lrows[key], rrows[key]
        where = f"keys={key[0]} bucket={key[1]}"
        for name in ("row_count", "unknown_count"):
            if getattr(a, name) != getattr(b, name):
                out.append(Mismatch(where, name, getattr(a, name), getattr(b, name)))
        if not values_equivalent(
            a.value, b.value, approximate=approximate, integer_metric=integer_metric
        ):
            out.append(Mismatch(where, "value", a.value, b.value))
    return out
