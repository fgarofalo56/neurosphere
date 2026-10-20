"""Interval estimates for evaluation statistics (PRP-16 item 3). Pure functions, stdlib only.

Method: the **Wilson score interval** for a binomial proportion (Wilson 1927).

    p  = successes / n,  z = Phi^-1(1 - (1 - level) / 2)
    centre = (p + z^2 / 2n) / (1 + z^2 / n)
    half   = z / (1 + z^2 / n) * sqrt(p (1 - p) / n + z^2 / 4n^2)
    interval = [centre - half, centre + half]

Why Wilson: the pilot label sets are small (tens of items) and rates sit near 0 or 1 (a 90%
grounded-answer target). The textbook Wald interval ``p +- z sqrt(p(1-p)/n)`` collapses to a
zero-width interval at 0/n and n/n and under-covers for small n; Wilson stays inside [0, 1], has
near-nominal coverage at small n and is never degenerate. The interval is a confidence interval on
the pilot-set rate; it is a target estimate, never a guarantee or an SLA.

Known case (tested): 45/50 at 95% gives [0.78640, 0.95652]. ``n == 0`` is not estimable: no
bounds, never a 0 rate.
"""

from __future__ import annotations

from math import sqrt
from statistics import NormalDist
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from neurosphere_core.errors import InvalidSchemaError

__all__ = ["Interval", "mean_difference_interval", "normal_quantile", "proportion_interval"]


class Interval(BaseModel):
    """Mirrors the contract ``uncertainty`` block: bounds are null exactly when not estimable."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    method: Literal["confidence_interval", "bootstrap", "not_estimable"]
    lower: float | None = None
    upper: float | None = None
    level: float | None = Field(default=None, gt=0.0, lt=1.0)
    standard_error: float | None = Field(default=None, ge=0.0)

    @classmethod
    def not_estimable(cls) -> Interval:
        return cls(method="not_estimable")


def _check_level(level: float) -> None:
    if not 0.0 < level < 1.0:
        raise InvalidSchemaError("level must be in (0, 1)", reason="invalid_level")


def normal_quantile(level: float) -> float:
    """Two-sided critical value ``z`` for a confidence ``level`` (1.95996 at 0.95)."""
    _check_level(level)
    return NormalDist().inv_cdf(1.0 - (1.0 - level) / 2.0)


def proportion_interval(successes: int, n: int, level: float = 0.95) -> Interval:
    """Wilson score interval for ``successes`` out of ``n`` (see the module docstring)."""
    _check_level(level)
    if n < 0 or successes < 0 or successes > n:
        raise InvalidSchemaError("need 0 <= successes <= n", reason="invalid_counts")
    if n == 0:
        return Interval.not_estimable()
    z = normal_quantile(level)
    p = successes / n
    denom = 1.0 + z * z / n
    centre = (p + z * z / (2.0 * n)) / denom
    half = z / denom * sqrt(p * (1.0 - p) / n + z * z / (4.0 * n * n))
    return Interval(
        method="confidence_interval",
        lower=max(0.0, centre - half),
        upper=min(1.0, centre + half),
        level=level,
        standard_error=sqrt(p * (1.0 - p) / n),
    )


def mean_difference_interval(differences: list[float], level: float = 0.95) -> Interval:
    """Normal-approximation interval ``mean +- z s / sqrt(n)`` for paired differences.

    Needs at least two values (a sample standard deviation); otherwise not estimable.
    """
    _check_level(level)
    n = len(differences)
    if n < 2:
        return Interval.not_estimable()
    mean = sum(differences) / n
    var = sum((d - mean) ** 2 for d in differences) / (n - 1)
    se = sqrt(var / n)
    z = normal_quantile(level)
    return Interval(
        method="confidence_interval",
        lower=mean - z * se,
        upper=mean + z * se,
        level=level,
        standard_error=se,
    )
