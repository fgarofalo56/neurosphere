"""Index definition: drift guard against SearchDocument, flags, ensure_index."""

from __future__ import annotations

from typing import Any

from neurosphere_core.search.azure.schema import (
    catalog_index_definition,
    ensure_index,
    to_azure_document,
)
from neurosphere_core.search.fixture.index import SearchDocument


def _doc() -> SearchDocument:
    return SearchDocument(
        id="commercial:acme:cat:agent:x",
        entity="agent",
        cloud="commercial",
        customer_id="acme",
        domain_id="commercial:acme:cat:domain:d",
        text="t",
    )


def test_every_serialised_field_exists_in_the_definition() -> None:
    fields = {f.name for f in catalog_index_definition().fields}
    assert set(to_azure_document(_doc())) == fields
    assert set(SearchDocument.model_fields) <= fields


def test_field_flags() -> None:
    by_name = {f.name: f for f in catalog_index_definition("idx").fields}
    assert by_name["id"].key is True
    for name in ("entity_id", "entity", "cloud", "customer_id", "domain_id"):
        assert by_name[name].filterable is True
        assert by_name[name].type == "Edm.String"
    assert by_name["text"].searchable is True
    assert catalog_index_definition("idx").name == "idx"


async def test_ensure_index_calls_create_or_update() -> None:
    calls: list[Any] = []

    class Admin:
        async def create_or_update_index(self, index: Any, **_kw: Any) -> None:
            calls.append(index)

    definition = catalog_index_definition()
    await ensure_index(Admin(), definition)
    assert calls == [definition]
