"""Shared setup for the migration integration tests (compose Cosmos vNext emulator).

Per G12 these tests assert document shape and versions only. Index behaviour and RU cost are
not exercised: the vNext emulator has no RU accounting and no range/composite indexes.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from azure.cosmos import PartitionKey
from neurosphere_core.migrations import (
    MigrationRunner,
    MigrationTarget,
    synthetic_snapshot,
)
from neurosphere_core.migrations.cosmos import CosmosDocumentStore, CosmosLedgerStore
from neurosphere_core.migrations.sample_steps import sample_steps

if TYPE_CHECKING:
    from azure.cosmos.aio import ContainerProxy, DatabaseProxy

DOCS = 8


@dataclass
class Env:
    docs: ContainerProxy
    ledgers: ContainerProxy
    name: str

    def runner(self, owner: str) -> MigrationRunner:
        return MigrationRunner(
            target=MigrationTarget.COSMOS_DOCUMENTS,
            name=self.name,
            steps=sample_steps(self.name),
            ledger_store=CosmosLedgerStore(self.ledgers),
            document_store=CosmosDocumentStore(self.docs),
            owner=owner,
        )

    async def documents(self) -> list[dict[str, Any]]:
        return [row async for row in self.docs.query_items("SELECT * FROM c")]


async def create_env(database: DatabaseProxy) -> Env:
    """Unique containers per run (partition key /id), seeded with synthetic documents."""
    name = f"mig_{uuid.uuid4().hex[:10]}"
    docs = await database.create_container_if_not_exists(
        id=name, partition_key=PartitionKey(path="/id")
    )
    ledgers = await database.create_container_if_not_exists(
        id=f"{name}_ledger", partition_key=PartitionKey(path="/id")
    )
    for doc in synthetic_snapshot(DOCS):
        await docs.create_item(doc)
    return Env(docs, ledgers, name)


async def drop_env(database: DatabaseProxy, env: Env) -> None:
    await database.delete_container(env.docs.id)
    await database.delete_container(env.ledgers.id)
