"""Cell clients (PRP-21 item 3).

A federating API reaches a cell only through :class:`CellClient`. The ONLY caller-derived input a
client sends is the caller's own ``Authorization`` header, forwarded unchanged: the cell validates
it and derives the ``IdentityScope`` itself. No ``domain_id``, ``customer_id`` or scope field is
ever sent, so a cell has nothing it could trust from the federator.

* :class:`InProcessCellClient` -- a cell in this process (tests, single-binary deployments); it
  runs the cell's own authenticator and scope source, not the federator's scope.
* :class:`HttpCellClient` -- a remote cell over https at the registered endpoint
  (``GET /api/v1/federation/cell-summary``). Endpoints come from operator config only.
"""

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Final, Protocol, runtime_checkable

import httpx
from neurosphere_core.aggregates import AggregateReader
from neurosphere_core.errors import (
    DependencyTransientError,
    ForbiddenError,
    UnauthorizedError,
)
from neurosphere_workers.federation import CellRef, CellSummary, compute_cell_summary
from pydantic import ValidationError

from neurosphere_api.authz import ScopeSource, TokenAuthenticator

__all__ = [
    "CELL_SUMMARY_PATH",
    "CellClient",
    "HttpCellClient",
    "InProcessCellClient",
]

CELL_SUMMARY_PATH: Final = "/api/v1/federation/cell-summary"
_MAX_RESPONSE_BYTES: Final = 1_000_000


@runtime_checkable
class CellClient(Protocol):
    async def fetch_summary(
        self, cell: CellRef, authorization: str | None, days: int
    ) -> CellSummary:
        """The caller's scope-filtered aggregate summary from ``cell``.

        Raises ``UnauthorizedError`` / ``ForbiddenError`` when the cell rejects the credential or
        derives no access, and ``DependencyTransientError`` when the cell cannot answer.
        """
        ...


class InProcessCellClient:
    """A cell hosted in this process. Scope is derived by THIS cell's own collaborators."""

    def __init__(
        self,
        *,
        authenticator: TokenAuthenticator,
        scope_source: ScopeSource,
        reader: AggregateReader,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._authenticator = authenticator
        self._scope_source = scope_source
        self._reader = reader
        self._clock = clock or (lambda: datetime.now(UTC))

    async def fetch_summary(
        self, cell: CellRef, authorization: str | None, days: int
    ) -> CellSummary:
        claims = await self._authenticator.authenticate(authorization)
        derivation = await self._scope_source.derive(claims)
        return await compute_cell_summary(
            self._reader, derivation.scope, cell=cell, days=days, clock=self._clock
        )


class HttpCellClient:
    """Remote cell over https. Uses the shared ``httpx.AsyncClient`` it is given (tests pass a
    ``MockTransport``); redirects are never followed so the credential cannot be re-sent."""

    def __init__(self, client: httpx.AsyncClient, *, timeout_seconds: float = 5.0) -> None:
        if not timeout_seconds > 0:
            raise ValueError("timeout_seconds must be positive")
        self._client = client
        self._timeout = timeout_seconds

    async def fetch_summary(
        self, cell: CellRef, authorization: str | None, days: int
    ) -> CellSummary:
        headers = {"Accept": "application/json"}
        if authorization:
            headers["Authorization"] = authorization
        url = cell.endpoint.rstrip("/") + CELL_SUMMARY_PATH
        try:
            response = await self._client.get(
                url,
                params={"days": str(days)},
                headers=headers,
                timeout=self._timeout,
                follow_redirects=False,
            )
        except httpx.HTTPError as exc:
            raise DependencyTransientError("cell unreachable", reason="cell_unreachable") from exc
        if response.status_code == 401:
            raise UnauthorizedError("cell rejected the credential", reason="cell_unauthorized")
        if response.status_code == 403:
            raise ForbiddenError("cell denied the request", reason="cell_forbidden")
        if response.status_code != 200 or len(response.content) > _MAX_RESPONSE_BYTES:
            raise DependencyTransientError("cell failed", reason="cell_failed")
        try:
            return CellSummary.model_validate_json(response.content)
        except ValidationError as exc:
            raise DependencyTransientError(
                "cell returned an invalid summary", reason="cell_invalid_response"
            ) from exc
