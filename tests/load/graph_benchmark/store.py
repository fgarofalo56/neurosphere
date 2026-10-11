"""Local seam over azure-cosmos. Only this module imports the SDK (lazily)."""

from __future__ import annotations

import base64
import importlib
import importlib.metadata
from typing import Any, Protocol

from .model import PartitionVariant

CREDENTIAL_MODES = ("emulator_key", "default_azure_credential")
# The vNext emulator accepts any key; this is a placeholder, not a credential.
_EMULATOR_PLACEHOLDER_KEY = base64.b64encode(b"emulator").decode()


class ContainerHandle(Protocol):
    name: str
    measures_request_charge: bool

    def upsert(self, doc: dict[str, Any]) -> None: ...

    def fetch_edges(self, src: str, pk: tuple[str, ...], limit: int) -> list[dict[str, Any]]: ...

    def last_request_charge(self) -> float | None: ...


class GraphStore(Protocol):
    database: str

    def create_container(self, name: str, variant: PartitionVariant) -> ContainerHandle: ...

    def close(self, *, cleanup: bool = True) -> None: ...


def sdk_version() -> str:
    try:
        return importlib.metadata.version("azure-cosmos")
    except importlib.metadata.PackageNotFoundError:
        return "not-installed"


class _SdkContainer:
    def __init__(self, container: Any, name: str, variant: PartitionVariant, measure: bool) -> None:
        self._c = container
        self.name = name
        self._variant = variant
        self.measures_request_charge = measure

    def upsert(self, doc: dict[str, Any]) -> None:
        self._c.upsert_item(doc)

    def fetch_edges(self, src: str, pk: tuple[str, ...], limit: int) -> list[dict[str, Any]]:
        key: Any = list(pk) if self._variant.hierarchical else pk[0]
        query = "SELECT TOP @n * FROM c WHERE c.doc_type = 'edge' AND c.src = @src"
        params = [{"name": "@n", "value": limit}, {"name": "@src", "value": src}]
        return list(self._c.query_items(query=query, parameters=params, partition_key=key))

    def last_request_charge(self) -> float | None:
        if not self.measures_request_charge:
            return None
        headers = getattr(self._c.client_connection, "last_response_headers", {}) or {}
        value = headers.get("x-ms-request-charge")
        return float(value) if value is not None else None


class SdkGraphStore:
    """azure-cosmos backed store. Creates a FRESH database; containers are never reused."""

    def __init__(
        self,
        endpoint: str,
        credential_mode: str,
        database: str,
        *,
        key: str | None = None,
        measure_request_charge: bool = False,
    ) -> None:
        from azure.cosmos import CosmosClient

        if credential_mode not in CREDENTIAL_MODES:
            raise ValueError(f"credential_mode must be one of {CREDENTIAL_MODES}")
        if credential_mode == "emulator_key":
            self._client = CosmosClient(
                endpoint, credential=key or _EMULATOR_PLACEHOLDER_KEY, connection_verify=False
            )
            self._measure = False  # emulator has no RU accounting
        else:
            # azure-identity is only needed for live runs; resolved lazily by name.
            identity = importlib.import_module("azure.identity")
            self._client = CosmosClient(endpoint, credential=identity.DefaultAzureCredential())
            self._measure = measure_request_charge
        self.database = database
        self._db = self._client.create_database(database)  # fails if it exists: always fresh

    def create_container(self, name: str, variant: PartitionVariant) -> ContainerHandle:
        from azure.cosmos import PartitionKey

        if variant.hierarchical:
            pk = PartitionKey(path=list(variant.paths), kind="MultiHash")
        else:
            pk = PartitionKey(path=variant.paths[0])
        # never create_container_if_not_exists: containers are always fresh
        container = self._db.create_container(id=name, partition_key=pk)
        return _SdkContainer(container, name, variant, self._measure)

    def close(self, *, cleanup: bool = True) -> None:
        if cleanup:
            self._client.delete_database(self.database)


class _MemContainer:
    measures_request_charge = False

    def __init__(self, name: str, variant: PartitionVariant) -> None:
        self.name = name
        self._variant = variant
        self.docs: dict[tuple[tuple[str, ...], str], dict[str, Any]] = {}
        self.queries: list[tuple[str, tuple[str, ...], int]] = []

    def upsert(self, doc: dict[str, Any]) -> None:
        self.docs[(self._variant.values(doc), doc["id"])] = dict(doc)

    def fetch_edges(self, src: str, pk: tuple[str, ...], limit: int) -> list[dict[str, Any]]:
        self.queries.append((src, pk, limit))
        rows = [
            d
            for (p, _), d in self.docs.items()
            if p == pk and d["doc_type"] == "edge" and d["src"] == src
        ]
        return sorted(rows, key=lambda d: d["seq"])[:limit]

    def last_request_charge(self) -> float | None:
        return None


class InMemoryGraphStore:
    """Offline stand-in used by unit tests (same seam, no network)."""

    def __init__(self, database: str = "mem") -> None:
        self.database = database
        self.containers: dict[str, _MemContainer] = {}
        self.closed = False

    def create_container(self, name: str, variant: PartitionVariant) -> ContainerHandle:
        if name in self.containers:
            raise ValueError(f"container {name} already exists (fresh containers only)")
        self.containers[name] = _MemContainer(name, variant)
        return self.containers[name]

    def close(self, *, cleanup: bool = True) -> None:
        self.closed = True
        if cleanup:
            self.containers.clear()
