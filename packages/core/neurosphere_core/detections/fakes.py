"""In-memory reader fakes for tests and the end-to-end slice (PRP-61 item 2)."""

from __future__ import annotations

from collections.abc import Sequence

from neurosphere_core.detections.models import (
    AccountRead,
    CatalogRead,
    DeploymentConfigRead,
    GatewayRead,
)

__all__ = [
    "FakeAiAccountInventory",
    "FakeCatalogDeploymentReader",
    "FakeDeploymentConfigReader",
    "FakeGatewayInventoryReader",
]


class FakeDeploymentConfigReader:
    def __init__(self, reads: Sequence[DeploymentConfigRead] = ()) -> None:
        self.reads = tuple(reads)
        self.error: Exception | None = None

    async def read(self) -> Sequence[DeploymentConfigRead]:
        if self.error is not None:
            raise self.error
        return self.reads


class FakeGatewayInventoryReader:
    def __init__(self, read: GatewayRead | None = None) -> None:
        self.result = read or GatewayRead()
        self.error: Exception | None = None

    async def read(self) -> GatewayRead:
        if self.error is not None:
            raise self.error
        return self.result


class FakeAiAccountInventory:
    def __init__(self, read: AccountRead | None = None) -> None:
        self.result = read or AccountRead()
        self.error: Exception | None = None

    async def read(self) -> AccountRead:
        if self.error is not None:
            raise self.error
        return self.result


class FakeCatalogDeploymentReader:
    def __init__(self, read: CatalogRead | None = None) -> None:
        self.result = read or CatalogRead()
        self.error: Exception | None = None

    async def read(self) -> CatalogRead:
        if self.error is not None:
            raise self.error
        return self.result
