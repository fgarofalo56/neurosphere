"""PRP-21 round 2 item 3: the forecast band uses a Student-t quantile for small samples."""

from decimal import Decimal

import pytest
from neurosphere_api.finops.service import (
    MIN_FIT_POINTS,
    T_975,
    Z_95,
    fit_and_predict,
    t_quantile_95,
)


def test_table_matches_the_published_values() -> None:
    assert t_quantile_95(1) == Decimal("12.706")
    assert t_quantile_95(3) == Decimal("3.182")
    assert t_quantile_95(10) == Decimal("2.228")
    assert t_quantile_95(30) == Decimal("2.042")
    assert t_quantile_95(120) == Decimal("1.980")


def test_between_table_rows_uses_the_wider_lower_df_and_large_samples_use_z() -> None:
    assert t_quantile_95(35) == T_975[30]
    assert t_quantile_95(45) == T_975[40]
    assert t_quantile_95(119) == T_975[60]
    assert t_quantile_95(121) == Z_95
    assert t_quantile_95(10_000) == Z_95


def test_quantile_is_monotonically_non_increasing_in_df() -> None:
    values = [t_quantile_95(df) for df in range(1, 200)]
    assert values == sorted(values, reverse=True)
    assert all(v >= Z_95 for v in values)


def test_invalid_df_is_rejected() -> None:
    with pytest.raises(ValueError, match="degrees of freedom"):
        t_quantile_95(0)


def test_small_sample_band_is_wider_than_the_normal_band() -> None:
    history = [(i, Decimal(10 + (i % 3))) for i in range(MIN_FIT_POINTS)]
    fitted = fit_and_predict(history, [MIN_FIT_POINTS])
    assert fitted is not None
    (value,), s = fitted
    half_width = value.upper - value.value
    # df = 3: the t band must exceed what z = 1.96 would have produced.
    assert half_width > 0
    ratio = (value.upper - value.value) / (Z_95 * s)
    assert ratio > 1


def test_too_few_points_stays_unavailable_never_a_number() -> None:
    assert fit_and_predict([(0, Decimal(1)), (1, Decimal(2))], [2]) is None
