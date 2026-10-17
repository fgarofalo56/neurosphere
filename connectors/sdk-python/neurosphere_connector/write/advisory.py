"""Read-only (advisory) connectors: every write-path method is unavailable."""

from __future__ import annotations

from neurosphere_core.errors import CapabilityUnavailableError

from neurosphere_connector.write.write_models import (
    ApplyResult,
    DryRunResult,
    RollbackResult,
    VerifyResult,
    WriteRequest,
)

__all__ = ["AdvisoryWriteMixin"]


class AdvisoryWriteMixin:
    """Mix into a read-only connector: ``advisory`` is True and writes raise.

    Raises ``CapabilityUnavailableError`` (reason ``read_only_connector``) so recommendations from
    such a connector can only ever be advisory, never executed.
    """

    @property
    def advisory(self) -> bool:
        return True

    @staticmethod
    def _unavailable() -> CapabilityUnavailableError:
        return CapabilityUnavailableError(
            "read_only_connector", "connector is read-only (advisory); it has no write support"
        )

    async def dry_run(self, request: WriteRequest) -> DryRunResult:
        raise self._unavailable()

    async def apply(self, request: WriteRequest) -> ApplyResult:
        raise self._unavailable()

    async def verify(self, request: WriteRequest) -> VerifyResult:
        raise self._unavailable()

    async def rollback(self, applied: ApplyResult) -> RollbackResult:
        raise self._unavailable()
