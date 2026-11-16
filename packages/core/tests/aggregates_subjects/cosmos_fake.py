"""Fake aggregate container: key path plus the exact WHERE clauses the store emits."""

from __future__ import annotations

import re
from typing import Any

from neurosphere_core.aggregates.subject import KEYS_PER_QUERY
from recommendations_cosmos.fake_container import (  # pyright: ignore[reportMissingImports]
    FakeContainer,
    Predicate,
)

_IN = re.compile(r"@k\d+")


def _in_clause(count: int) -> str:
    return "c.series_key IN (" + ", ".join(f"@k{i}" for i in range(count)) + ")"


def _in_predicate(count: int) -> Predicate:
    def check(doc: dict[str, Any], params: dict[str, Any]) -> bool:
        return doc.get("series_key") in {params[f"@k{i}"] for i in range(count)}

    return check


CLAUSES: dict[str, Predicate] = {
    "c.customer_id = @customer": lambda d, p: d["customer_id"] == p["@customer"],
    "c.doc_type = 'aggregate'": lambda d, p: d["doc_type"] == "aggregate",
    "c.domain_id = @domain": lambda d, p: d["domain_id"] == p["@domain"],
    "c.metric = 'subject'": lambda d, p: d.get("metric") == "subject",
    "c.grain = 'hour'": lambda d, p: d["grain"] == "hour",
    "c.grain = @grain": lambda d, p: d["grain"] == p["@grain"],
    "c.bucket_start >= @start": lambda d, p: d["bucket_start"] >= p["@start"],
    "c.bucket_start < @end": lambda d, p: d["bucket_start"] < p["@end"],
    "c.bucket_start = @start": lambda d, p: d["bucket_start"] == p["@start"],
    "c.subject_kind = @kind": lambda d, p: d.get("subject_kind") == p["@kind"],
    **{_in_clause(n): _in_predicate(n) for n in range(1, KEYS_PER_QUERY + 1)},
}


def new_container() -> FakeContainer:
    return FakeContainer(["/customer_id"], CLAUSES)
