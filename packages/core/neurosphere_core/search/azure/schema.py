"""Azure AI Search index schema, document key encoding and index bootstrap (PRP-60 item 1).

Azure document keys may contain only letters, digits, underscore, dash and equals, but canonical
catalog ids are ``cloud:customer:source:type:local``. The key (``id``) is therefore the URL-safe
base64 of the canonical id without padding (reversible and collision-free), and the canonical id
is stored in a separate retrievable, filterable ``entity_id`` field. Authorization filters and
the returned hit id use ``entity_id``; ``id`` is an opaque key.

``ensure_index`` creates or updates the index through an injected ``SearchIndexClient``-shaped
object. It needs index-write RBAC, so callers opt in explicitly (``NS_SEARCH_ENSURE_INDEX``).
"""

from __future__ import annotations

import base64
import binascii
import re
from typing import Any, Final, Protocol

from azure.search.documents.indexes.models import (
    SearchableField,
    SearchFieldDataType,
    SearchIndex,
    SimpleField,
)

from neurosphere_core.search.azure.filters import FIELD_ENTITY_ID
from neurosphere_core.search.fixture.index import SearchDocument

__all__ = [
    "FIELD_ENTITY_ID",
    "IndexAdminBackend",
    "catalog_index_definition",
    "decode_document_key",
    "encode_document_key",
    "ensure_index",
    "to_azure_document",
]

DEFAULT_INDEX_NAME: Final = "neurosphere-catalog"
#: Azure caps a document key at 1024 characters.
_MAX_KEY: Final = 1024
_KEY_RE: Final = re.compile(r"^[A-Za-z0-9_-]+\Z")


class IndexAdminBackend(Protocol):
    """The slice of ``azure.search.documents.indexes.aio.SearchIndexClient`` used here."""

    async def create_or_update_index(self, index: Any, **kwargs: Any) -> Any:
        """Create the index or update it in place."""
        ...


def encode_document_key(canonical_id: str) -> str:
    """Return the Azure-safe key for ``canonical_id`` (URL-safe base64, no padding)."""
    if not canonical_id or not canonical_id.isascii():
        raise ValueError("canonical id must be a non-empty ASCII string")
    key = base64.urlsafe_b64encode(canonical_id.encode("ascii")).decode("ascii").rstrip("=")
    if len(key) > _MAX_KEY:
        raise ValueError("canonical id too long for an Azure document key")
    return key


def decode_document_key(encoded: str) -> str:
    """Return the canonical id for ``encoded``; reject keys the encoder cannot emit."""
    if not _KEY_RE.match(encoded) or len(encoded) % 4 == 1:
        raise ValueError("not a canonical document key")
    try:
        decoded = base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)).decode("ascii")
    except (binascii.Error, UnicodeDecodeError):
        raise ValueError("not a canonical document key") from None
    if encode_document_key(decoded) != encoded:  # reject non-canonical padding bits
        raise ValueError("not a canonical document key")
    return decoded


def to_azure_document(document: SearchDocument) -> dict[str, Any]:
    """Map a ``SearchDocument`` to the Azure index document (encoded key + ``entity_id``)."""
    body = document.model_dump()
    body["id"] = encode_document_key(document.id)
    body[FIELD_ENTITY_ID] = document.id
    return body


def catalog_index_definition(name: str = DEFAULT_INDEX_NAME) -> SearchIndex:
    """The catalog index: opaque key, filterable scope fields, searchable ``text``."""
    string = SearchFieldDataType.String
    return SearchIndex(
        name=name,
        fields=[
            SimpleField(name="id", type=string, key=True, filterable=True),
            SimpleField(name=FIELD_ENTITY_ID, type=string, filterable=True),
            SimpleField(name="entity", type=string, filterable=True),
            SimpleField(name="cloud", type=string, filterable=True),
            SimpleField(name="customer_id", type=string, filterable=True),
            SimpleField(name="domain_id", type=string, filterable=True),
            SearchableField(name="text", type=string),
        ],
    )


async def ensure_index(index_client: IndexAdminBackend, definition: SearchIndex) -> None:
    """Create or update ``definition`` through ``index_client`` (idempotent)."""
    await index_client.create_or_update_index(definition)
