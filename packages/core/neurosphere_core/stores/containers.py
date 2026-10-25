"""The one declarative registry of every Cosmos container of the ``neurosphere`` database.

Each :class:`ContainerSpec` names a container, its partition key paths (one path = ``Hash``,
several = hierarchical ``MultiHash``) and its container-level default TTL (``None`` = TTL off,
``-1`` = TTL on with no default expiry, so per-item ``ttl`` applies). Store modules keep their
own in-module constants; ``packages/core/tests/stores_registry`` (and the API-side parity test
for the stores that live in ``services/api``) pin every entry to those constants, so this table
cannot silently drift from the code that reads and writes the documents.

Provisioning rules (PRP-29 C16):

* ``NS_ENV=local`` only: :func:`ensure_local_containers` creates the database and every
  container on the emulator (idempotent ``create_*_if_not_exists``).
* Every other environment never creates anything here. Containers come from IaC (PRP-32's
  Bicep consumes :func:`export_document`, written to ``infra/compose/cosmos-containers.json``);
  a missing container is a readiness failure, never a silent create.

The sandbox keeps its own database (``sandbox-neurosphere``) and is not declared here.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any, Final, Literal, Protocol

from azure.cosmos import PartitionKey

from neurosphere_core.cloud import Settings
from neurosphere_core.errors import InvalidSchemaError, ValidationIssue

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

DEFAULT_DATABASE: Final = "neurosphere"
EXPORT_SCHEMA_VERSION: Final = "1.0.0"
#: TTL switched on with no container default: only documents carrying ``ttl`` expire.
TTL_PER_ITEM: Final = -1

PartitionKind = Literal["Hash", "MultiHash"]


@dataclass(frozen=True, slots=True)
class ContainerSpec:
    """One container: name, partition key paths, default TTL and the owning store module."""

    name: str
    partition_key_paths: tuple[str, ...]
    owner: str
    default_ttl: int | None = None
    notes: str = field(default="", compare=False)

    def __post_init__(self) -> None:
        if not self.name or not 1 <= len(self.partition_key_paths) <= 3:
            raise ValueError("a container needs a name and one to three partition key paths")
        for path in self.partition_key_paths:
            if not path.startswith("/") or len(path) < 2:
                raise ValueError("partition key paths start with '/'")
        ttl = self.default_ttl
        if ttl is not None and ttl != TTL_PER_ITEM and ttl < 1:
            raise ValueError("default_ttl is None, -1 or a positive number of seconds")

    @property
    def kind(self) -> PartitionKind:
        return "MultiHash" if len(self.partition_key_paths) > 1 else "Hash"

    def partition_key(self) -> PartitionKey:
        """The SDK key definition (hierarchical keys need ``kind="MultiHash"``)."""
        if self.kind == "Hash":
            return PartitionKey(path=self.partition_key_paths[0])
        return PartitionKey(path=list(self.partition_key_paths), kind="MultiHash")

    def to_json(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "partition_key": {"paths": list(self.partition_key_paths), "kind": self.kind},
            "default_ttl": self.default_ttl,
            "owner": self.owner,
        }


_CUSTOMER: Final = ("/customer_id",)
_CUSTOMER_DOMAIN: Final = ("/customer_id", "/domain_id")

#: Every container, in a fixed order (the export sorts by name; this order is documentation).
CONTAINERS: Final[tuple[ContainerSpec, ...]] = (
    # --- identity (PRP-06) ---------------------------------------------------------------
    ContainerSpec("policy", _CUSTOMER, "neurosphere_core.auth.scope.cosmos_repository"),
    ContainerSpec(
        "revocations",
        ("/principal_id",),
        "neurosphere_core.auth.revocation.cosmos_store",
        default_ttl=TTL_PER_ITEM,
        notes="per-item ttl = revocation retention",
    ),
    # --- catalog, telemetry and cost (PRP-07/10/14) ---------------------------------------
    ContainerSpec(
        "catalog",
        ("/domain",),
        "neurosphere_core.catalog.repo.cosmos",
        notes=(
            "flat_domain shape (the repository default and the always-available fallback); "
            "the hierarchical /tenant,/domain,/shard shape needs a NEW container (PRP-13)"
        ),
    ),
    ContainerSpec("aggregates", _CUSTOMER, "neurosphere_core.aggregates.cosmos"),
    ContainerSpec("cost-ledger", _CUSTOMER, "neurosphere_workers.ingestion.wiring"),
    ContainerSpec("outbox", _CUSTOMER, "neurosphere_workers.ingestion.wiring"),
    ContainerSpec("outbox-checkpoints", _CUSTOMER, "neurosphere_workers.ingestion.wiring"),
    ContainerSpec("ingestion-accepted", _CUSTOMER, "neurosphere_workers.ingestion.cosmos_stores"),
    ContainerSpec("ingestion-watermarks", _CUSTOMER, "neurosphere_workers.ingestion.cosmos_stores"),
    # --- action plane, audit, copilot, reports, MCP, deploy (PRP-06/17/19/20/22) -----------
    ContainerSpec("action_intents", _CUSTOMER_DOMAIN, "neurosphere_core.actions.cosmos_store"),
    ContainerSpec("action_execution_control", _CUSTOMER, "neurosphere_core.actions.cosmos_store"),
    ContainerSpec("audit", ("/chain_id",), "neurosphere_core.audit.cosmos_store"),
    ContainerSpec("audit_tail", ("/chain_id",), "neurosphere_core.audit.cosmos_store"),
    ContainerSpec(
        "copilot_conversations",
        ("/owner",),
        "neurosphere_api.copilot.cosmos_store",
        default_ttl=TTL_PER_ITEM,
    ),
    ContainerSpec("reports", _CUSTOMER_DOMAIN, "neurosphere_api.reports.cosmos_store"),
    ContainerSpec("mcp_servers", ("/id",), "neurosphere_core.mcp.cosmos_store"),
    ContainerSpec(
        "deploy_register", ("/deployment_id",), "neurosphere_core.deploy.register.cosmos_store"
    ),
    # --- new in PRP-29 (items 2 and 3 implement the stores) ------------------------------
    ContainerSpec(
        "recommendations", _CUSTOMER_DOMAIN, "neurosphere_core.recommendations.cosmos_store"
    ),
    ContainerSpec("evaluation_runs", _CUSTOMER_DOMAIN, "neurosphere_core.evaluation.cosmos_store"),
    ContainerSpec(
        "evaluation_results", _CUSTOMER_DOMAIN, "neurosphere_core.evaluation.cosmos_store"
    ),
    ContainerSpec(
        "price_snapshots",
        ("/snapshot_id",),
        "neurosphere_core.pricing.cosmos_store",
        notes=(
            "every protocol read is by snapshot id or a global scan; Cosmos ids are unique per "
            "logical partition, so keying by snapshot id keeps the put-conflict rule exact"
        ),
    ),
    ContainerSpec("hitl_items", _CUSTOMER_DOMAIN, "neurosphere_core.hitl.cosmos_store"),
    ContainerSpec(
        "hitl_decisions",
        ("/review_item_id",),
        "neurosphere_core.hitl.cosmos_store",
        notes=(
            "DecisionStore receives only (decision_id, document); the ApprovalDecision document "
            "carries review_item_id but no customer_id/domain_id, and list_for_item reads by it"
        ),
    ),
    ContainerSpec(
        "catalog_review_queue",
        _CUSTOMER_DOMAIN,
        "neurosphere_core.catalog.review_queue_cosmos",
        notes="ReviewItem carries customer_id and domain_id (it has no 'domain' field)",
    ),
    ContainerSpec(
        "lifecycle_requests",
        _CUSTOMER,
        "neurosphere_core.lifecycle.cosmos",
        notes="stores are bound to one customer and stamp customer_id",
    ),
    ContainerSpec("lifecycle_holds", _CUSTOMER, "neurosphere_core.lifecycle.cosmos"),
    ContainerSpec("lifecycle_mappings", _CUSTOMER, "neurosphere_core.lifecycle.cosmos"),
)


def _check_unique(specs: Iterable[ContainerSpec]) -> None:
    names = [s.name for s in specs]
    if len(names) != len(set(names)):
        raise ValueError("container names must be unique")


_check_unique(CONTAINERS)
_BY_NAME: Final[Mapping[str, ContainerSpec]] = {s.name: s for s in CONTAINERS}


def container_spec(name: str) -> ContainerSpec:
    """The declared spec of ``name``; an undeclared container is a ``KeyError``."""
    return _BY_NAME[name]


def export_document(specs: Iterable[ContainerSpec] = CONTAINERS) -> dict[str, Any]:
    """Deterministic, value-free description for IaC (PRP-32 Bicep): sorted by name."""
    return {
        "schema_version": EXPORT_SCHEMA_VERSION,
        "generated_from": "neurosphere_core.stores.containers",
        "database": DEFAULT_DATABASE,
        "containers": [s.to_json() for s in sorted(specs, key=lambda s: s.name)],
    }


def export_json(specs: Iterable[ContainerSpec] = CONTAINERS) -> str:
    """:func:`export_document` as stable JSON text (sorted keys, two-space indent, final LF)."""
    return json.dumps(export_document(specs), indent=2, sort_keys=True) + "\n"


class _Client(Protocol):
    """The slice of ``azure.cosmos.aio.CosmosClient`` used here (fakes satisfy it in tests)."""

    async def create_database_if_not_exists(self, id: str) -> Any: ...


def _refuse_outside_local(settings: Settings) -> None:
    if settings.env != "local":
        detail = "containers are created only when NS_ENV=local; provision them with IaC"
        raise InvalidSchemaError(detail, errors=[ValidationIssue("/env", detail)], reason="config")


async def ensure_local_containers(
    client: _Client,
    settings: Settings,
    *,
    database: str = DEFAULT_DATABASE,
    specs: Iterable[ContainerSpec] = CONTAINERS,
) -> tuple[str, ...]:
    """Create the database and every declared container on the local emulator (idempotent).

    Refuses (``invalid_schema``, reason ``config``) before any call when ``NS_ENV`` is not
    ``local``. Returns the container names ensured, in declaration order.
    """
    _refuse_outside_local(settings)
    ordered = tuple(specs)
    _check_unique(ordered)
    db = await client.create_database_if_not_exists(id=database)
    for spec in ordered:
        options: dict[str, Any] = {}
        if spec.default_ttl is not None:
            options["default_ttl"] = spec.default_ttl
        await db.create_container_if_not_exists(
            id=spec.name, partition_key=spec.partition_key(), **options
        )
    return tuple(s.name for s in ordered)
