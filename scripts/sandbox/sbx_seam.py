"""Thin seam over azure-cosmos and azure-eventhub (PRP-05 replaces this with the real adapters).

Nothing here logs connection strings or keys.
"""

from __future__ import annotations

import hashlib
import json
import threading
import time
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from typing import Any

from azure.cosmos import CosmosClient, PartitionKey
from azure.cosmos import exceptions as cosmos_exc
from azure.eventhub import EventData, EventHubConsumerClient, EventHubProducerClient
from sbx_guard import (
    cosmos_settings,
    eventhubs_connection_string,
    require_sandbox_name,
)

HUB = "telemetry"
DATABASE = "sandbox-neurosphere"


@dataclass
class SeedStats:
    created: int = 0
    updated: int = 0
    unchanged: int = 0
    per_container: dict[str, dict[str, int]] = field(default_factory=dict)

    def bump(self, container: str, outcome: str) -> None:
        setattr(self, outcome, getattr(self, outcome) + 1)
        bucket = self.per_container.setdefault(
            container, {"created": 0, "updated": 0, "unchanged": 0}
        )
        bucket[outcome] += 1


class CosmosSeam:
    def __init__(self, env: dict[str, str] | None = None) -> None:
        endpoint, key = cosmos_settings(env)
        self._client = CosmosClient(endpoint, credential=key)

    def ensure_database(self, name: str) -> Any:
        require_sandbox_name(name, "database")
        return self._client.create_database_if_not_exists(id=name)

    def ensure_container(self, db: Any, name: str) -> Any:
        require_sandbox_name(name, "container")
        return db.create_container_if_not_exists(id=name, partition_key=PartitionKey(path="/id"))

    def upsert_all(
        self, container: Any, name: str, docs: Iterable[dict[str, Any]], stats: SeedStats
    ) -> None:
        """Idempotent load: read by id, write only when absent or different."""
        require_sandbox_name(name, "container")
        for doc in docs:
            try:
                existing = container.read_item(item=doc["id"], partition_key=doc["id"])
            except cosmos_exc.CosmosResourceNotFoundError:
                container.upsert_item(doc)
                stats.bump(name, "created")
                continue
            if all(existing.get(k) == v for k, v in doc.items()):
                stats.bump(name, "unchanged")
            else:
                container.upsert_item(doc)
                stats.bump(name, "updated")

    def count(self, db_name: str, container_name: str) -> int:
        require_sandbox_name(db_name, "database")
        require_sandbox_name(container_name, "container")
        container = self._client.get_database_client(db_name).get_container_client(container_name)
        return sum(
            1
            for _ in container.query_items(
                query="SELECT c.id FROM c", enable_cross_partition_query=True
            )
        )

    def list_sandbox_databases(self) -> list[str]:
        names = [d["id"] for d in self._client.list_databases()]
        return [n for n in names if n.startswith("sandbox-")]

    def drop_database(self, name: str) -> None:
        require_sandbox_name(name, "database")
        try:
            self._client.delete_database(name)
        except cosmos_exc.CosmosResourceNotFoundError:
            pass


def partition_for(line: bytes, partition_ids: list[str]) -> str:
    """Stable partition by trace_id so a trace stays ordered; unparsable lines hash the bytes."""
    key = line
    try:
        obj = json.loads(line)
        if isinstance(obj, dict) and isinstance(obj.get("trace_id"), str):
            key = obj["trace_id"].encode("ascii", "replace")
    except (ValueError, UnicodeDecodeError):
        pass
    digest = hashlib.blake2b(key, digest_size=4).digest()
    return partition_ids[int.from_bytes(digest, "big") % len(partition_ids)]


class HubSeam:
    def __init__(self, env: dict[str, str] | None = None, hub: str = HUB) -> None:
        self._conn = eventhubs_connection_string(env)
        self._hub = hub

    def _producer(self) -> EventHubProducerClient:
        return EventHubProducerClient.from_connection_string(self._conn, eventhub_name=self._hub)

    def event_count(self) -> int:
        """Events currently retained across all partitions (from sequence numbers)."""
        with self._producer() as producer:
            total = 0
            for pid in producer.get_partition_ids():
                props = producer.get_partition_properties(pid)
                if not props["is_empty"]:
                    total += (
                        props["last_enqueued_sequence_number"]
                        - props["beginning_sequence_number"]
                        + 1
                    )
            return total

    def publish(self, lines: Iterator[bytes], rate: float = 0.0, chunk: int = 100) -> int:
        """Send raw line bytes (malformed ones included) preserving per-partition order."""
        sent = 0
        started = time.monotonic()
        with self._producer() as producer:
            pids = list(producer.get_partition_ids())
            pending: dict[str, list[bytes]] = {p: [] for p in pids}
            in_chunk = 0

            def flush() -> None:
                for pid, items in pending.items():
                    if not items:
                        continue
                    batch = producer.create_batch(partition_id=pid)
                    for body in items:
                        try:
                            batch.add(EventData(body))
                        except ValueError:
                            producer.send_batch(batch)
                            batch = producer.create_batch(partition_id=pid)
                            batch.add(EventData(body))
                    producer.send_batch(batch)
                    items.clear()

            for line in lines:
                pending[partition_for(line, pids)].append(line)
                sent += 1
                in_chunk += 1
                if in_chunk >= chunk:
                    flush()
                    in_chunk = 0
                    if rate > 0:
                        delay = started + sent / rate - time.monotonic()
                        if delay > 0:
                            time.sleep(delay)
            flush()
        return sent

    def consume(self, consumer_group: str, expected: int, timeout: float = 60.0) -> list[bytes]:
        """Read from the start of every partition until `expected` bodies or `timeout` seconds."""
        bodies: list[bytes] = []
        lock = threading.Lock()
        done = threading.Event()

        def on_event(_ctx: Any, event: Any) -> None:
            if event is None:
                return
            with lock:
                bodies.append(b"".join(bytes(part) for part in event.body))
                if len(bodies) >= expected:
                    done.set()

        client = EventHubConsumerClient.from_connection_string(
            self._conn, consumer_group=consumer_group, eventhub_name=self._hub
        )
        worker = threading.Thread(
            target=lambda: client.receive(on_event=on_event, starting_position="-1"), daemon=True
        )
        worker.start()
        done.wait(timeout)
        time.sleep(1.5)  # catch over-delivery beyond `expected`
        client.close()
        worker.join(5)
        return bodies
