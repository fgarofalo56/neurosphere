from __future__ import annotations

import pytest
from neurosphere_core.payload import sanitize_cost_center


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("CC-4410", "CC-4410"),
        (" CC/1.a-b ", "CC/1.a-b"),
        ("CC\x00-1", "CC-1"),
        ("N/A", None),
        ("n/a", None),
        ("", None),
        ("-leading", None),
        ("has space", None),
        ("x" * 129, None),
        (None, None),
        (7, None),
    ],
)
def test_sanitize(raw: object, expected: str | None) -> None:
    assert sanitize_cost_center(raw) == expected
