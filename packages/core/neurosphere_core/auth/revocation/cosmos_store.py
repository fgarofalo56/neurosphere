"""Cosmos NoSQL revocation store over an injected async client (``neurosphere_core.clients``).

Container layout: partition key path ``/principal_id``; one document per principal
(``id = revocation.<pseudonym>``, ``doc_type = revocation``) carrying a per-item ``ttl`` of the
configured retention. The container must have TTL enabled (``defaultTtl = -1``: on, no default
expiry) or the per-item ``ttl`` is ignored; container provisioning belongs to the infra PRPs.

SDK surface: ``read_item`` (point read), ``create_item`` and ``replace_item`` with an
``IfNotModified`` ETag condition, so a concurrent older revocation can never overwrite a later
one. No queries are built from request input.

Fail closed: not-found is the only failure mapped to ``None``. Every other SDK or transport
failure, including 401/403 from the store, raises ``dependency_transient`` (503); a document that
does not validate raises ``dependency_transient`` with ``upstream_invalid`` (502). It is never
reported as "not revoked". Messages never echo SDK text, document content or principal ids.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Final

from azure.core import MatchConditions
from azure.cosmos.aio import ContainerProxy, CosmosClient
from azure.cosmos.exceptions import (
    CosmosAccessConditionFailedError,
    CosmosResourceExistsError,
    CosmosResourceNotFoundError,
)
from pydantic import ValidationError

from neurosphere_core.auth.revocation.model import (
    DEFAULT_REVOCATION_RETENTION_SECONDS,
    RevocationEntry,
    revocation_document_id,
)
from neurosphere_core.errors import DependencyTransientError

__all__ = [
    "DEFAULT_REVOCATION_CONTAINER",
    "MAX_PUT_ATTEMPTS",
    "PARTITION_KEY_PATH",
    "REVOCATION_DOC_TYPE",
    "CosmosRevocationStore",
]

DEFAULT_REVOCATION_CONTAINER: Final = "revocations"
PARTITION_KEY_PATH: Final = "/principal_id"
REVOCATION_DOC_TYPE: Final = "revocation"
MAX_PUT_ATTEMPTS: Final = 3
_STORAGE_FIELDS: Final = frozenset({"id", "doc_type", "ttl"})


def _unavailable() -> DependencyTransientError:
    return DependencyTransientError(
        "revocation store unavailable", reason="revocation_store_unavailable"
    )


class CosmosRevocationStore:
    def __init__(
        self,
        container: ContainerProxy,
        *,
        retention_seconds: int = DEFAULT_REVOCATION_RETENTION_SECONDS,
    ) -> None:
        self._container = container
        self._retention = retention_seconds

    @classmethod
    def from_client(
        cls,
        client: CosmosClient,
        *,
        database: str,
        container: str = DEFAULT_REVOCATION_CONTAINER,
        retention_seconds: int = DEFAULT_REVOCATION_RETENTION_SECONDS,
    ) -> CosmosRevocationStore:
        return cls(
            client.get_database_client(database).get_container_client(container),
            retention_seconds=retention_seconds,
        )

    async def _read(self, principal_id: str) -> tuple[RevocationEntry, str] | None:
        doc_id = revocation_document_id(principal_id)
        try:
            raw = await self._container.read_item(item=doc_id, partition_key=principal_id)
        except CosmosResourceNotFoundError:
            return None
        except Exception as exc:
            raise _unavailable() from exc
        try:
            entry = RevocationEntry.model_validate(_strip(raw))
        except ValidationError as exc:
            raise _invalid("revocation entry failed validation") from exc
        if entry.principal_id != principal_id:
            raise _invalid("revocation entry belongs to another principal")
        return entry, str(raw.get("_etag", ""))

    async def get(self, principal_id: str) -> RevocationEntry | None:
        found = await self._read(principal_id)
        return None if found is None else found[0]

    async def put(self, entry: RevocationEntry) -> RevocationEntry:
        body = {
            **entry.model_dump(mode="json"),
            "id": revocation_document_id(entry.principal_id),
            "doc_type": REVOCATION_DOC_TYPE,
            "ttl": self._retention,
        }
        for _ in range(MAX_PUT_ATTEMPTS):
            found = await self._read(entry.principal_id)
            try:
                if found is None:
                    await self._container.create_item(body=body)
                    return entry
                existing, etag = found
                if existing.revoked_at >= entry.revoked_at:
                    return existing
                await self._container.replace_item(
                    item=body["id"],
                    body=body,
                    etag=etag,
                    match_condition=MatchConditions.IfNotModified,
                )
                return entry
            except (CosmosResourceExistsError, CosmosAccessConditionFailedError):
                continue  # another writer won; re-read and compare again
            except Exception as exc:
                raise _unavailable() from exc
        raise DependencyTransientError(
            "revocation store write contended", reason="revocation_store_conflict"
        )


def _strip(document: Mapping[str, Any]) -> dict[str, Any]:
    """Drop Cosmos system properties (``_rid``, ``_etag``...) and storage-only fields."""
    return {k: v for k, v in document.items() if not k.startswith("_") and k not in _STORAGE_FIELDS}


def _invalid(detail: str) -> DependencyTransientError:
    return DependencyTransientError(
        detail, reason="revocation_entry_invalid", upstream_invalid=True
    )
