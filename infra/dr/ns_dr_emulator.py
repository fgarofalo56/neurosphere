"""Emulator connection settings for the DR scripts.

No credential literal lives here. The Cosmos emulator ignores its key, so a placeholder is
derived at runtime; the Azurite development account is resolved by the installed
azure-storage-blob SDK from the ``UseDevelopmentStorage`` shorthand (same approach as
``tests/integration/ingestion/support.py``). The values stay in memory: never written, never
printed. Environment overrides use the repo's existing variable names. ``.env`` is never read.
"""

from __future__ import annotations

import base64
import os
from dataclasses import dataclass

from azure.storage.blob.aio import ContainerClient

ENV_COSMOS_ENDPOINT = "NS_COSMOS_ENDPOINT"
ENV_COSMOS_KEY = "NS_COSMOS_KEY"
ENV_BLOB_CONNECTION_STRING = "NS_BLOB_CONNECTION_STRING"
DEFAULT_COSMOS_ENDPOINT = "http://localhost:8081"
EVENTHUBS_NAMESPACE = "localhost"  # fully_qualified_namespace used for checkpoint blobs


@dataclass(frozen=True)
class Connections:
    cosmos_endpoint: str
    cosmos_key: str
    blob_connection_string: str

    def __repr__(self) -> str:  # never leak the secret-bearing fields
        return f"Connections(cosmos_endpoint={self.cosmos_endpoint!r}, ...)"


def azurite_connection_string() -> str:
    """The full Azurite development connection string, assembled at runtime from the SDK."""
    probe = ContainerClient.from_connection_string("UseDevelopmentStorage=true;", "probe")
    credential = probe.credential
    name = credential.account_name  # type: ignore[union-attr]
    key = credential.account_key  # type: ignore[union-attr]
    endpoint = probe.primary_endpoint.rsplit("/", 1)[0]
    return (
        "DefaultEndpointsProtocol=http;"
        + f"AccountName={name};"
        + f"AccountKey={key};"
        + (f"BlobEndpoint={endpoint};")
    )


def load_connections(env: dict[str, str] | None = None) -> Connections:
    source = os.environ if env is None else env
    return Connections(
        cosmos_endpoint=source.get(ENV_COSMOS_ENDPOINT, DEFAULT_COSMOS_ENDPOINT),
        cosmos_key=source.get(ENV_COSMOS_KEY)
        or base64.b64encode(b"emulator-ignores-this").decode(),
        blob_connection_string=source.get(ENV_BLOB_CONNECTION_STRING)
        or azurite_connection_string(),
    )
