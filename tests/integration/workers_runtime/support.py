"""Helpers for the worker-roles integration test (emulators only, synthetic sandbox data).

Never starts or stops docker compose: it only checks that the emulators already answer. All
names (database, blob containers) are unique per run and removed afterwards. No key-shaped
literal lives here: the Cosmos key is a runtime-built dummy (the emulator ignores it) and the
Azurite connection string is assembled from the installed SDK's development account.
"""

from __future__ import annotations

import base64
import json
import socket
import sys
import tempfile
from pathlib import Path
from typing import Any

from azure.storage.blob.aio import ContainerClient

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.append(str(REPO_ROOT))

COSMOS_ENDPOINT = "http://127.0.0.1:8081"
HUB = "telemetry"
EVENTHUBS_CONNECTION = (
    "Endpoint=sb://127.0.0.1;SharedAccessKeyName=RootManageSharedAccessKey;"
    "SharedAccessKey=SAS_KEY_VALUE;UseDevelopmentEmulator=true;"
)
AZURITE_SHORTHAND = "UseDevelopmentStorage=true;"

#: Fixed, public, non-secret identifiers for the worker principal (random-looking GUIDs).
WORKER_TENANT_ID = "0f1e2d3c-4b5a-4968-8776-a5b4c3d2e1f0"
WORKER_OBJECT_ID = "6c1d2e3f-4a5b-4c6d-8e7f-90a1b2c3d4e5"

Doc = dict[str, Any]


def reachable(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=2):
            return True
    except OSError:
        return False


def emulators_up() -> bool:
    """Cosmos (8081), Azurite (10000) and the Event Hubs emulator (5672) all answer."""
    return all(reachable("127.0.0.1", p) for p in (8081, 10000, 5672))


def dummy_cosmos_key() -> str:
    return base64.b64encode(b"emulator-ignores-this").decode()


def azurite_connection_string() -> str:
    """Full emulator connection string, assembled at runtime from the SDK's development account."""
    probe = ContainerClient.from_connection_string(AZURITE_SHORTHAND, "probe")
    credential = probe.credential
    name, key = credential.account_name, credential.account_key  # type: ignore[union-attr]
    endpoint = probe.primary_endpoint.rsplit("/", 1)[0]
    return (
        "DefaultEndpointsProtocol=http;"
        + f"AccountName={name};"
        + (f"AccountKey={key};BlobEndpoint={endpoint};")
    )


def sandbox_trace_bundle() -> tuple[list[Doc], list[Doc]]:
    """(telemetry of ONE trace holding delegation, model and tool spans, a few cost records)."""
    from sandbox.config import PROFILES, BadEventRates, GenerateConfig
    from sandbox.generate import generate

    rates = BadEventRates(duplicate=0.0, out_of_order=0.0, malformed=0.0, missing_optional=0.0)
    cfg = GenerateConfig(seed=7, profile=PROFILES["tiny"], cloud="commercial", rates=rates)
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp)
        generate(cfg, out)

        def read(name: str) -> list[Doc]:
            lines = (out / name).read_text(encoding="utf-8").splitlines()
            return [json.loads(line) for line in lines if line]

        telemetry, cost = read("telemetry.ndjson"), read("cost.ndjson")
    traces: dict[str, list[Doc]] = {}
    for doc in telemetry:
        traces.setdefault(doc["trace_id"], []).append(doc)
    for trace_id in sorted(traces):
        spans = traces[trace_id]
        if {"delegation", "model_call", "tool_call"} <= {d["span_kind"] for d in spans}:
            return sorted(spans, key=lambda d: d["event_time"]), cost[:5]
    raise AssertionError("sandbox bundle has no delegation trace")
