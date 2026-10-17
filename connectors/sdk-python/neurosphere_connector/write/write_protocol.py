"""The ``WriteConnector`` protocol: what PRP-17's action executor calls on a connector."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Protocol, runtime_checkable

from neurosphere_contracts.connectors.v1.connector_manifest import ConnectorManifest

from neurosphere_connector.write.write_models import (
    ApplyResult,
    DryRunResult,
    RollbackResult,
    VerifyResult,
    WriteRequest,
    check_diff_against_state,
)

__all__ = ["WriteConnector", "build_verify_result"]


@runtime_checkable
class WriteConnector(Protocol):
    """A connector that can really change its target. ``advisory`` must mirror the manifest."""

    @property
    def manifest(self) -> ConnectorManifest: ...

    @property
    def advisory(self) -> bool: ...

    async def dry_run(self, request: WriteRequest) -> DryRunResult:
        """Plan the change against ``request.target_version``; write nothing."""
        ...

    async def apply(self, request: WriteRequest) -> ApplyResult:
        """Make the change on the real target (never just catalog metadata)."""
        ...

    async def verify(self, request: WriteRequest) -> VerifyResult:
        """Read the target back and report the observed state against the requested diff."""
        ...

    async def rollback(self, applied: ApplyResult) -> RollbackResult:
        """Undo a previously applied change."""
        ...


def build_verify_result(
    request: WriteRequest,
    observed_state: Mapping[str, Any],
    *,
    observed_version: str | None = None,
) -> VerifyResult:
    """Helper for implementers: ``observed_state`` must come from reading the real target."""
    return VerifyResult(
        target=request.target,
        requested_diff=request.proposed_diff,
        observed_state=dict(observed_state),
        observed_version=observed_version,
        checks=check_diff_against_state(request.proposed_diff, observed_state),
    )
