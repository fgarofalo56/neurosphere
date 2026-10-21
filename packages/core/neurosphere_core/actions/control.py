"""Emergency disable (kill switch) for action execution, per customer.

:class:`ExecutionControl` reads and sets the flag. FAIL CLOSED: when the control store cannot be
read, ``get`` raises ``dependency_transient`` (reason ``execution_control_unavailable``) and every
caller must treat execution as DISABLED, never as enabled. :func:`require_execution_enabled` is
the one check the service and the executor use: it raises ``capability_unavailable`` (reason
``emergency_disabled``) when the flag is set and lets the outage error through otherwise.

A customer with no stored control document is enabled (the flag is opt-in to stop). Disabling
never touches intents: queued or executing intents stay where they are and resume, through the
normal recheck, once execution is re-enabled.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Protocol, Self, runtime_checkable

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from neurosphere_core.actions.errors import EMERGENCY_DISABLED, EXECUTION_CONTROL_UNAVAILABLE
from neurosphere_core.actions.models import CUSTOMER_PATTERN, REASON_PATTERN
from neurosphere_core.errors import (
    CapabilityUnavailableError,
    DependencyTransientError,
    NeuroSphereError,
)

__all__ = [
    "ExecutionControl",
    "ExecutionControlState",
    "InMemoryExecutionControl",
    "control_unavailable",
    "require_execution_enabled",
]


class ExecutionControlState(BaseModel):
    """Current kill-switch value. ``changed_by`` is an actor PSEUDONYM, never a principal id."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    customer_id: Annotated[str, Field(pattern=CUSTOMER_PATTERN)]
    disabled: bool = False
    reason: Annotated[str | None, Field(pattern=REASON_PATTERN)] = None
    changed_by: Annotated[str | None, Field(pattern=r"^[a-z0-9][a-z0-9._-]{0,127}$")] = None
    changed_at: AwareDatetime | None = None

    @model_validator(mode="after")
    def _disabled_needs_reason(self) -> Self:
        if self.disabled and self.reason is None:
            raise ValueError("a disabled execution control must state a reason")
        return self


@runtime_checkable
class ExecutionControl(Protocol):
    async def get(self, customer_id: str) -> ExecutionControlState:
        """Current state; outage raises ``dependency_transient`` (treat as disabled)."""
        ...

    async def set(
        self,
        customer_id: str,
        *,
        disabled: bool,
        reason: str | None,
        changed_by: str,
        now: datetime,
    ) -> ExecutionControlState:
        """Store a new state (last write wins) and return it."""
        ...


def control_unavailable() -> DependencyTransientError:
    return DependencyTransientError(
        "execution control unavailable; execution is treated as disabled",
        reason=EXECUTION_CONTROL_UNAVAILABLE,
    )


async def require_execution_enabled(
    control: ExecutionControl, customer_id: str
) -> ExecutionControlState:
    """Raise unless execution is enabled for ``customer_id`` (fail closed on any failure)."""
    try:
        state = await control.get(customer_id)
    except NeuroSphereError:
        raise
    except Exception as exc:
        raise control_unavailable() from exc
    if state.disabled:
        raise CapabilityUnavailableError(EMERGENCY_DISABLED, "action execution is disabled")
    return state


class InMemoryExecutionControl:
    """Per-process control store for tests and the sandbox; ``fail_with`` simulates an outage."""

    def __init__(self) -> None:
        self._states: dict[str, ExecutionControlState] = {}
        self.error: Exception | None = None

    def fail_with(self, error: Exception | None) -> None:
        self.error = error

    async def get(self, customer_id: str) -> ExecutionControlState:
        error = self.error
        if error is not None:
            raise error
        return self._states.get(customer_id) or ExecutionControlState(customer_id=customer_id)

    async def set(
        self,
        customer_id: str,
        *,
        disabled: bool,
        reason: str | None,
        changed_by: str,
        now: datetime,
    ) -> ExecutionControlState:
        error = self.error
        if error is not None:
            raise error
        state = ExecutionControlState(
            customer_id=customer_id,
            disabled=disabled,
            reason=reason,
            changed_by=changed_by,
            changed_at=now,
        )
        self._states[customer_id] = state
        return state
