"""Register storage port and in-memory implementation."""

from __future__ import annotations

from typing import Protocol

from neurosphere_core.deploy.register.models import (
    ConsentRecord,
    Ownership,
    ResourceRow,
    normalize_id,
)
from neurosphere_core.errors import ForbiddenError


def check_no_downgrade(existing: ResourceRow | None, incoming: ResourceRow) -> None:
    """Ownership may never move from reused/shared to created."""
    if (
        existing is not None
        and existing.ownership is not Ownership.CREATED
        and incoming.ownership is Ownership.CREATED
    ):
        raise ForbiddenError("register ownership cannot be downgraded from reused/shared")


class RegisterStore(Protocol):
    async def put_row(self, row: ResourceRow) -> None: ...

    async def get_row(self, deployment_id: str, resource_id: str) -> ResourceRow | None: ...

    async def list_rows(self, deployment_id: str) -> list[ResourceRow]: ...

    async def put_consent(self, consent: ConsentRecord) -> None: ...

    async def list_consents(self, deployment_id: str) -> list[ConsentRecord]: ...


class InMemoryRegisterStore:
    def __init__(self) -> None:
        self._rows: dict[tuple[str, str], ResourceRow] = {}
        self._consents: dict[tuple[str, str], ConsentRecord] = {}

    async def put_row(self, row: ResourceRow) -> None:
        key = (row.deployment_id, normalize_id(row.resource_id))
        check_no_downgrade(self._rows.get(key), row)
        self._rows[key] = row

    async def get_row(self, deployment_id: str, resource_id: str) -> ResourceRow | None:
        return self._rows.get((deployment_id, normalize_id(resource_id)))

    async def list_rows(self, deployment_id: str) -> list[ResourceRow]:
        return [r for (d, _), r in self._rows.items() if d == deployment_id]

    async def put_consent(self, consent: ConsentRecord) -> None:
        self._consents[(consent.deployment_id, consent.consent_id)] = consent

    async def list_consents(self, deployment_id: str) -> list[ConsentRecord]:
        return [c for (d, _), c in self._consents.items() if d == deployment_id]
