"""``BaseConnector``: the class every NeuroSphere connector subclasses.

A subclass supplies a contract-valid ``manifest`` and does its work inside ``guarded_call`` so
success, rate limiting and failures feed ``health()``. Credentials are fetched per call through
``credential()`` (never stored on the instance), which is what makes rotation take effect
without a restart. All public methods are async.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable

from neurosphere_contracts.connectors.v1.connector_manifest import ConnectorManifest

from neurosphere_connector.health import (
    Clock,
    CoverageReport,
    FreshnessReport,
    HealthReport,
    HealthTracker,
    utc_now,
)
from neurosphere_connector.vault import CredentialBroker, SecretValue

__all__ = ["BaseConnector"]


class BaseConnector(ABC):
    """Base class: manifest, health, coverage, freshness and credential access."""

    def __init__(
        self, *, credentials: CredentialBroker | None = None, clock: Clock = utc_now
    ) -> None:
        self._credentials = credentials
        self._tracker = HealthTracker(clock=clock)
        self.closed = False

    @property
    @abstractmethod
    def manifest(self) -> ConnectorManifest:
        """The connector's registration manifest (use ``build_manifest``)."""

    async def health(self) -> HealthReport:
        """Current health, including rate-limit status, coverage and freshness."""
        return self._tracker.snapshot()

    async def coverage(self) -> CoverageReport:
        """Fraction of expected sources that answered on the last successful call."""
        return self._tracker.snapshot().coverage

    async def freshness(self) -> FreshnessReport:
        """Data lag on the last successful call; ``lag_ms`` is None when unknown."""
        return self._tracker.snapshot().freshness

    async def credential(self, name: str) -> SecretValue:
        """Resolve a declared credential now (always via the broker, so rotation applies)."""
        if self._credentials is None:
            raise RuntimeError("connector was created without a credential broker")
        return await self._credentials.get(name)

    async def guarded_call[T](
        self,
        operation: Callable[[], Awaitable[T]],
        *,
        freshness: Callable[[T], FreshnessReport | None] | None = None,
        coverage: Callable[[T], CoverageReport | None] | None = None,
    ) -> T:
        """Run ``operation``, recording the outcome in health; errors are re-raised unchanged."""
        try:
            result = await operation()
        except Exception as exc:
            self._tracker.record_error(exc)
            raise
        self._tracker.record_success(
            freshness=freshness(result) if freshness else None,
            coverage=coverage(result) if coverage else None,
        )
        return result

    async def close(self) -> None:
        """Release resources; subclasses extend and call ``await super().close()``."""
        self.closed = True
