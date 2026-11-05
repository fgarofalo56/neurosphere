"""#27 only billing observations can be invoiced; #28 ledger ids are collision-safe."""

from __future__ import annotations

import pytest
from neurosphere_core.ledger import allocation_id, entry_id

from .builders import obs


@pytest.mark.parametrize("source", ["gateway", "application"])
def test_invoiced_requires_billing_source(source: str) -> None:
    with pytest.raises(ValueError, match="billing"):
        obs(1, source=source, kind="invoiced", amount="5.00", version=None)


def test_billing_invoiced_is_allowed() -> None:
    assert obs(1, source="billing", kind="invoiced", amount="5.00", version=None).kind == "invoiced"


def test_entry_id_pipe_collision_regression() -> None:
    assert entry_id("a|b", "c", "d") != entry_id("a", "b|c", "d")
    assert entry_id("a", "b", "c|d") != entry_id("a", "b|c", "d")
    assert allocation_id("a|b", "c") != allocation_id("a", "b|c")


def test_ids_are_deterministic_and_64_hex() -> None:
    first = entry_id("c", "r", "k")
    assert first == entry_id("c", "r", "k")
    assert len(first) == 64
