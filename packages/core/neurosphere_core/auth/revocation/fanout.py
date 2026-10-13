"""Revocation fan-out: cache-invalidation hooks and push-session closers (PRP-06 C13).

A revocation calls EVERY registered cache invalidator (for example
``ScopeDeriver.invalidate_principal`` and ``CachedRevocationChecker.invalidate_principal``) and
``close_for_principal`` on EVERY registered ``PushSessionRegistry`` (the WebSocket gateway is
PRP-18; only the interface exists here). Hooks run one after another, each under its own timeout.
A hook that raises or times out is logged and counted; it never aborts the remaining hooks and
``fan_out`` itself never raises (``asyncio.CancelledError`` still propagates).

Logging rule: a failure is logged with the hook kind, the hook's registered name and the
exception CLASS name only. No principal id, object id, UPN, e-mail or exception message (which
could carry any of those) is ever logged.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
import re
from collections.abc import Callable, Container
from dataclasses import dataclass
from typing import Final, Literal, Protocol, runtime_checkable

__all__ = [
    "DEFAULT_HOOK_TIMEOUT_SECONDS",
    "CacheInvalidator",
    "FanoutReport",
    "HookKind",
    "PushSessionRegistry",
    "RevocationHookRegistry",
]

_log = logging.getLogger(__name__)

DEFAULT_HOOK_TIMEOUT_SECONDS: Final = 5.0
_NAME_RE: Final = re.compile(r"[a-z0-9][a-z0-9._-]{0,63}")

HookKind = Literal["cache_invalidator", "push_registry"]

#: Called with the canonical principal id. May be sync or async; the return value is ignored.
CacheInvalidator = Callable[[str], object]


@runtime_checkable
class PushSessionRegistry(Protocol):
    """Live push channels (WebSocket, SSE) for one replica. Implemented by PRP-18."""

    async def close_for_principal(self, principal_id: str) -> int:
        """Close every open session of ``principal_id``; return how many were closed."""
        ...


@dataclass(frozen=True, slots=True)
class FanoutReport:
    """Outcome of one fan-out. Names are registration names, never principal data."""

    invalidators_called: int
    invalidators_failed: tuple[str, ...]
    push_registries_called: int
    push_registries_failed: tuple[str, ...]
    sessions_closed: int

    @property
    def complete(self) -> bool:
        return not self.invalidators_failed and not self.push_registries_failed


class RevocationHookRegistry:
    def __init__(
        self,
        *,
        hook_timeout_seconds: float = DEFAULT_HOOK_TIMEOUT_SECONDS,
        logger: logging.Logger | None = None,
    ) -> None:
        if hook_timeout_seconds <= 0:
            raise ValueError("hook_timeout_seconds must be positive")
        self._timeout = hook_timeout_seconds
        self._log = logger or _log
        self._invalidators: dict[str, CacheInvalidator] = {}
        self._registries: dict[str, PushSessionRegistry] = {}

    @staticmethod
    def _check_name(name: str, taken: Container[str]) -> None:
        if _NAME_RE.fullmatch(name) is None:
            raise ValueError("hook name must match [a-z0-9][a-z0-9._-]{0,63}")
        if name in taken:
            raise ValueError("hook name already registered")

    def register_cache_invalidator(self, name: str, invalidator: CacheInvalidator) -> None:
        if not callable(invalidator):
            raise TypeError("cache invalidator must be callable")
        self._check_name(name, self._invalidators)
        self._invalidators[name] = invalidator

    def register_push_registry(self, name: str, registry: PushSessionRegistry) -> None:
        if not isinstance(registry, PushSessionRegistry):
            raise TypeError("push registry must implement close_for_principal")
        self._check_name(name, self._registries)
        self._registries[name] = registry

    @property
    def cache_invalidator_names(self) -> tuple[str, ...]:
        return tuple(self._invalidators)

    @property
    def push_registry_names(self) -> tuple[str, ...]:
        return tuple(self._registries)

    async def fan_out(self, principal_id: str) -> FanoutReport:
        inv_failed: list[str] = []
        for name, invalidator in self._invalidators.items():
            if not await self._run("cache_invalidator", name, invalidator, principal_id):
                inv_failed.append(name)
        push_failed: list[str] = []
        closed = 0
        for name, registry in self._registries.items():
            result: list[object] = []
            ok = await self._run(
                "push_registry",
                name,
                registry.close_for_principal,
                principal_id,
                sink=result,
            )
            if not ok:
                push_failed.append(name)
            elif result and isinstance(result[0], int) and not isinstance(result[0], bool):
                closed += max(0, result[0])
        return FanoutReport(
            invalidators_called=len(self._invalidators),
            invalidators_failed=tuple(inv_failed),
            push_registries_called=len(self._registries),
            push_registries_failed=tuple(push_failed),
            sessions_closed=closed,
        )

    async def _run(
        self,
        kind: HookKind,
        name: str,
        hook: Callable[[str], object],
        principal_id: str,
        *,
        sink: list[object] | None = None,
    ) -> bool:
        try:
            async with asyncio.timeout(self._timeout):
                outcome = hook(principal_id)
                if inspect.isawaitable(outcome):
                    outcome = await outcome
        except Exception as exc:  # a failing hook must not abort the others
            self._log.warning(
                "revocation hook failed",
                extra={"hook_kind": kind, "hook": name, "error_type": type(exc).__name__},
            )
            return False
        if sink is not None:
            sink.append(outcome)
        return True
