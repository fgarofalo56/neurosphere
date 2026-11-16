"""Azure document key encoding: reversible, Azure-safe, rejects non-canonical input."""

from __future__ import annotations

import re

import pytest
from hypothesis import given
from hypothesis import strategies as st
from neurosphere_core.search.azure.schema import (
    decode_document_key,
    encode_document_key,
    to_azure_document,
)
from neurosphere_core.search.fixture.index import SearchDocument

_AZURE_KEY = re.compile(r"^[A-Za-z0-9_=-]+\Z")
_CANONICAL = st.from_regex(
    r"(commercial|government):[a-z0-9._-]{1,12}:[a-z0-9._-]{1,12}:[a-z_]{1,12}:[a-z0-9._/=-]{1,24}",
    fullmatch=True,
)


@given(_CANONICAL)
def test_round_trip_and_alphabet(canonical: str) -> None:
    key = encode_document_key(canonical)
    assert _AZURE_KEY.match(key) and "=" not in key and ":" not in key
    assert decode_document_key(key) == canonical


def test_distinct_ids_get_distinct_keys() -> None:
    a = encode_document_key("commercial:acme:cat:agent:a_b")
    b = encode_document_key("commercial:acme:cat:agent:a:b")
    assert a != b


@pytest.mark.parametrize("bad", ["", "a:b", "ab cd", "A", "AB==", "%%%%", "_-_-_"])
def test_decode_rejects_non_canonical(bad: str) -> None:
    with pytest.raises(ValueError):
        decode_document_key(bad)


@pytest.mark.parametrize("bad", ["", "café:x"])
def test_encode_rejects_empty_and_non_ascii(bad: str) -> None:
    with pytest.raises(ValueError):
        encode_document_key(bad)


def test_azure_document_maps_key_and_canonical_id() -> None:
    doc = SearchDocument(
        id="commercial:acme:cat:agent:x",
        entity="agent",
        cloud="commercial",
        customer_id="acme",
        domain_id="commercial:acme:cat:domain:d",
        text="hello",
    )
    out = to_azure_document(doc)
    assert out["entity_id"] == doc.id
    assert decode_document_key(out["id"]) == doc.id
    assert out["text"] == "hello"
