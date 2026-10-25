"""The recommendation container fake: key paths and the exact WHERE clauses the store emits."""

from __future__ import annotations

from typing import Any

from neurosphere_core.recommendations.cosmos_store import RECOMMENDATION_PARTITION_KEY_PATHS

from .fake_container import FakeContainer, Predicate


def _q(doc: dict[str, Any], p: dict[str, Any]) -> bool:
    needle = p["@q"]
    return needle in doc["kind"].lower() or any(needle in s.lower() for s in doc["subject_ids"])


CLAUSES: dict[str, Predicate] = {
    "c.doc_type = @doc_type": lambda d, p: d["doc_type"] == p["@doc_type"],
    "c.customer_id = @customer": lambda d, p: d["customer_id"] == p["@customer"],
    "c.domain_id = @domain": lambda d, p: d["domain_id"] == p["@domain"],
    "c.cloud = @cloud": lambda d, p: d["cloud"] == p["@cloud"],
    "c.sort_key > @after": lambda d, p: d["sort_key"] > p["@after"],
    "c.kind = @kind": lambda d, p: d["kind"] == p["@kind"],
    (
        "(CONTAINS(LOWER(c.kind), @q) OR "
        "EXISTS(SELECT VALUE s FROM s IN c.subject_ids WHERE CONTAINS(LOWER(s), @q)))"
    ): _q,
}


def new_container() -> FakeContainer:
    return FakeContainer(RECOMMENDATION_PARTITION_KEY_PATHS, CLAUSES)
