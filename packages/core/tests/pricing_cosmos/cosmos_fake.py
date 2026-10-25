"""Price snapshot container fake: key path and the exact WHERE clauses the store emits."""

from __future__ import annotations

from neurosphere_core.pricing.cosmos_store import PRICE_SNAPSHOT_PARTITION_KEY_PATH

from .fake_container import FakeSyncContainer, Predicate

CLAUSES: dict[str, Predicate] = {
    "ARRAY_CONTAINS(c.clouds, @cloud)": lambda d, p: p["@cloud"] in d["clouds"],
    "c.effective_date <= @on": lambda d, p: d["effective_date"] <= p["@on"],
}


def new_container() -> FakeSyncContainer:
    return FakeSyncContainer((PRICE_SNAPSHOT_PARTITION_KEY_PATH,), CLAUSES)
