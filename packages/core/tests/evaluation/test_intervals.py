"""Wilson interval, tested against a known textbook case and the edges."""

from __future__ import annotations

import pytest
from neurosphere_core.errors import InvalidSchemaError
from neurosphere_core.evaluation.calibration import mean_difference_interval, proportion_interval


def test_wilson_known_case_45_of_50() -> None:
    iv = proportion_interval(45, 50, 0.95)
    assert iv.method == "confidence_interval"
    assert iv.level == 0.95
    assert iv.lower == pytest.approx(0.78640, abs=1e-5)
    assert iv.upper == pytest.approx(0.95652, abs=1e-5)


def test_zero_successes_has_nonzero_upper_bound() -> None:
    iv = proportion_interval(0, 10)
    assert iv.lower == pytest.approx(0.0, abs=1e-12)
    assert iv.upper == pytest.approx(0.27753, abs=1e-5)


def test_all_successes_has_lower_bound_below_one() -> None:
    iv = proportion_interval(10, 10)
    assert iv.upper == pytest.approx(1.0, abs=1e-12)
    assert iv.lower == pytest.approx(0.72247, abs=1e-5)


def test_n_zero_is_not_estimable_with_no_bounds() -> None:
    iv = proportion_interval(0, 0)
    assert iv.method == "not_estimable"
    assert iv.lower is None
    assert iv.upper is None
    assert iv.level is None


def test_higher_level_is_wider() -> None:
    a, b = proportion_interval(8, 10, 0.90), proportion_interval(8, 10, 0.99)
    assert a.lower is not None and a.upper is not None
    assert b.lower is not None and b.upper is not None
    assert b.upper - b.lower > a.upper - a.lower


@pytest.mark.parametrize(("s", "n", "level"), [(-1, 5, 0.95), (6, 5, 0.95), (1, 5, 1.0), (1, 5, 0)])
def test_invalid_inputs_rejected(s: int, n: int, level: float) -> None:
    with pytest.raises(InvalidSchemaError):
        proportion_interval(s, n, level)


def test_mean_difference_interval() -> None:
    iv = mean_difference_interval([0.1, 0.3, 0.2, 0.2])
    assert iv.lower is not None and iv.upper is not None
    assert iv.lower < 0.2 < iv.upper
    assert mean_difference_interval([0.1]).method == "not_estimable"
