"""Component status registry of the composed application (PRP-29 C6, wire contract "Readiness").

Every component has exactly one state:

* ``ok``: built and installed on ``app.state``;
* ``failed``: could not be built; carries a reason code (``[a-z][a-z0-9_]*``, never a config
  value, host, key or exception text);
* ``disabled``: an optional component that is deliberately off (for example copilot without
  ``NS_COPILOT_MODE``);
* ``not_built``: nothing built it (yet). Item 1's placeholder builders report this.

Readiness: a REQUIRED component blocks readiness unless ``ok``; an OPTIONAL component blocks
only when ``failed`` (misconfigured), never when ``disabled`` or ``not_built``. Startup steps
(``cosmos_containers``: emulator bootstrap when local, existence check elsewhere) start ``ok``
and block only when they ran and ``failed``.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Final, Literal

__all__ = [
    "OPTIONAL_COMPONENTS",
    "REQUIRED_COMPONENTS",
    "STARTUP_STEPS",
    "ComponentRegistry",
    "ComponentState",
    "ComponentStatus",
    "is_reason_code",
]

REQUIRED_COMPONENTS: Final = (
    "authz",
    "policy_store",
    "revocation",
    "catalog",
    "aggregates",
    "ledger",
    "federation",
    "evaluation",
    "recommendations",
    "review_router",
    "hitl",
    "replay",
    "map",
    "audit",
    "action_plane",
    "reports",
    "mcp_admin",
    "realtime",
)
OPTIONAL_COMPONENTS: Final = ("copilot", "mcp_server", "ingest", "scan", "gateway_plane")
#: Startup steps that are not components but still gate readiness when they fail.
STARTUP_STEPS: Final = ("cosmos_containers",)

ComponentState = Literal["ok", "failed", "disabled", "not_built"]
_REASON: Final = re.compile(r"[a-z][a-z0-9_]{0,63}")


def is_reason_code(value: str) -> bool:
    return _REASON.fullmatch(value) is not None


@dataclass(frozen=True, slots=True)
class ComponentStatus:
    name: str
    state: ComponentState
    required: bool
    reason: str | None = None
    step: bool = False

    @property
    def code(self) -> str:
        """The reason code for a failure, else the state name."""
        return self.reason if self.state == "failed" and self.reason else self.state

    @property
    def blocks_readiness(self) -> bool:
        if self.state == "ok":
            return False
        if self.required:
            return True
        return self.state == "failed"


class ComponentRegistry:
    """Known component names in a fixed order; unknown names are a programming error."""

    def __init__(
        self,
        required: Iterable[str] = REQUIRED_COMPONENTS,
        optional: Iterable[str] = OPTIONAL_COMPONENTS,
        steps: Iterable[str] = STARTUP_STEPS,
    ) -> None:
        self._required = tuple(required)
        self._optional = tuple(optional)
        self._steps = tuple(steps)
        names = (*self._required, *self._optional, *self._steps)
        if len(names) != len(set(names)):
            raise ValueError("component names must be unique")
        self._statuses: dict[str, ComponentStatus] = {
            name: ComponentStatus(name, "not_built", required=name not in self._optional)
            for name in (*self._required, *self._optional)
        }
        # Steps start "ok": a step that never runs (no Cosmos client) gates nothing.
        for name in self._steps:
            self._statuses[name] = ComponentStatus(name, "ok", required=True, step=True)
        self._reported: set[str] = set()

    @property
    def components(self) -> tuple[str, ...]:
        return (*self._required, *self._optional)

    def is_known(self, name: str) -> bool:
        return name in self._statuses and name not in self._steps

    def set(self, name: str, state: ComponentState, reason: str | None = None) -> None:
        current = self._statuses.get(name)
        if current is None:
            raise KeyError(f"unknown component: {name}")
        if state == "failed":
            if reason is None or not is_reason_code(reason):
                raise ValueError("a failed component needs a reason code [a-z][a-z0-9_]*")
        elif reason is not None:
            raise ValueError("only a failed component carries a reason")
        if state == "disabled" and current.required:
            raise ValueError(f"required component {name} cannot be disabled")
        self._statuses[name] = ComponentStatus(
            name, state, required=current.required, reason=reason, step=current.step
        )
        self._reported.add(name)

    def ok(self, name: str) -> None:
        self.set(name, "ok")

    def failed(self, name: str, reason: str) -> None:
        self.set(name, "failed", reason)

    def disabled(self, name: str) -> None:
        self.set(name, "disabled")

    def not_built(self, name: str) -> None:
        self.set(name, "not_built")

    def reported(self, name: str) -> bool:
        return name in self._reported

    def get(self, name: str) -> ComponentStatus:
        return self._statuses[name]

    def snapshot(self) -> tuple[ComponentStatus, ...]:
        """Every component then every step, in declaration order."""
        return tuple(self._statuses[n] for n in (*self.components, *self._steps))

    @property
    def ready(self) -> bool:
        return not any(status.blocks_readiness for status in self._statuses.values())

    def blocking(self) -> tuple[ComponentStatus, ...]:
        return tuple(s for s in self.snapshot() if s.blocks_readiness)
