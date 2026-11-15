"""What the lifecycle routes read from ``app.state.lifecycle`` (installed by the builder)."""

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime

from neurosphere_core.audit import AuditRepository
from neurosphere_core.lifecycle.jobs import JobStore
from neurosphere_core.lifecycle.policy import UNSET, PolicyState
from neurosphere_core.lifecycle.targets import HoldRegistry, RequestQueue

__all__ = ["STATE_ATTRIBUTE", "LifecycleApiState"]

STATE_ATTRIBUTE = "lifecycle"


def _now() -> datetime:
    return datetime.now(UTC)


@dataclass
class LifecycleApiState:
    jobs: JobStore
    holds: HoldRegistry
    queue: RequestQueue
    audit: AuditRepository
    #: ``dry_run`` or ``execute``: what the worker is configured with (same env on both sides).
    mode: str = "dry_run"
    policy: PolicyState = UNSET
    clock: Callable[[], datetime] = field(default=_now)

    def chain_id(self, customer_id: str) -> str:
        """The engine's audit chain for this customer, so API and worker records interleave."""
        return f"lifecycle.{customer_id}"
