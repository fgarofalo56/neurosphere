"""Declarative Cosmos container registry (PRP-29 item 1, C16).

``containers.CONTAINERS`` is the single table of container names, partition keys and TTLs;
``ensure_local_containers`` bootstraps the emulator when ``NS_ENV=local``; ``export_json`` is the
deterministic export written to ``infra/compose/cosmos-containers.json`` by
``python -m neurosphere_core.stores`` (PRP-32 consumes it for Bicep).
"""

from neurosphere_core.stores.containers import (
    CONTAINERS,
    DEFAULT_DATABASE,
    EXPORT_SCHEMA_VERSION,
    TTL_PER_ITEM,
    ContainerSpec,
    PartitionKind,
    container_spec,
    ensure_local_containers,
    export_document,
    export_json,
)

__all__ = [
    "CONTAINERS",
    "DEFAULT_DATABASE",
    "EXPORT_SCHEMA_VERSION",
    "TTL_PER_ITEM",
    "ContainerSpec",
    "PartitionKind",
    "container_spec",
    "ensure_local_containers",
    "export_document",
    "export_json",
]
