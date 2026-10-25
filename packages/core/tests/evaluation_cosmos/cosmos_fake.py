"""Evaluation container fakes: key paths and the exact WHERE clauses the store emits."""

from __future__ import annotations

from typing import Any

from neurosphere_core.evaluation.cosmos_store import EVALUATION_PARTITION_KEY_PATHS

from .fake_container import FakeContainer, Predicate


def _has_dimension(doc: dict[str, Any], p: dict[str, Any]) -> bool:
    return any(s["dimension"] == p["@dimension"] for s in doc["scores"])


CLAUSES: dict[str, Predicate] = {
    "c.doc_type = @doc_type": lambda d, p: d["doc_type"] == p["@doc_type"],
    "c.customer_id = @customer": lambda d, p: d["customer_id"] == p["@customer"],
    "c.domain_id = @domain": lambda d, p: d["domain_id"] == p["@domain"],
    "c.cloud = @cloud": lambda d, p: d["cloud"] == p["@cloud"],
    "c.sort_key > @after": lambda d, p: d["sort_key"] > p["@after"],
    "c.subject_id = @subject": lambda d, p: d["subject_id"] == p["@subject"],
    "EXISTS(SELECT VALUE s FROM s IN c.scores WHERE s.dimension = @dimension)": _has_dimension,
}


def new_container() -> FakeContainer:
    return FakeContainer(EVALUATION_PARTITION_KEY_PATHS, CLAUSES)
