"""The allowlisted copilot tool registry and its single entry point, ``ToolRegistry.invoke``.

``invoke(name, raw_args, scope)`` is the only way a model-chosen call reaches a tool:

1. Only registered tool names resolve; anything else is ``ToolNotRegisteredError``.
2. Any top-level key shaped like a scope (``SCOPE_SHAPED_KEYS``) is logged by NAME and the call
   is refused. The value is never read: "ignored" is implemented as never used, logged, refused.
3. Any other key the tool does not declare is refused too.
4. Remaining arguments are validated against the tool's Pydantic model (extra keys forbidden).
5. The tool runs under a clamped wall-clock budget with the server-derived scope.

Logs and sink events carry key names only (bounded), never argument values or prompt text.
"""

from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Any, Final, Protocol

from pydantic import ValidationError

from neurosphere_core.auth.scope import Permission
from neurosphere_core.copilot.tools.args import ToolArgs
from neurosphere_core.copilot.tools.errors import (
    ArgumentNotAllowedError,
    ScopeArgumentRefusedError,
    ToolNotRegisteredError,
    ToolTimeoutError,
)
from neurosphere_core.copilot.tools.models import ToolResult
from neurosphere_core.errors import InvalidSchemaError, ValidationIssue
from neurosphere_core.scope import IdentityScope

__all__ = [
    "DEFAULT_TIMEOUT_MS",
    "MAX_TIMEOUT_MS",
    "SCOPE_SHAPED_KEYS",
    "RefusalEvent",
    "RefusalSink",
    "ToolHandler",
    "ToolRegistry",
    "ToolSpec",
]

logger = logging.getLogger("neurosphere.copilot.tools")

#: Normalized (lowercase, ``-``/``_``/space removed) names that look like authorization scope.
#: A model must never supply these; the server derives them.
SCOPE_SHAPED_KEYS: Final = frozenset(
    {
        "domainid",
        "domainids",
        "domain",
        "domains",
        "customerid",
        "customer",
        "tenantid",
        "tenant",
        "alloweddomains",
        "allowedresources",
        "scope",
        "scopehash",
        "identityscope",
        "principalid",
        "principal",
        "roles",
        "role",
        "permissions",
        "cloud",
        "policyversion",
        "subscriptionid",
        "workspaceid",
    }
)

DEFAULT_TIMEOUT_MS: Final = 5_000
MAX_TIMEOUT_MS: Final = 10_000
_MAX_LOGGED_KEYS: Final = 8
_MAX_KEY_LENGTH: Final = 64
_SAFE_KEY: Final = re.compile(r"^[A-Za-z0-9_.-]+$")

ToolHandler = Callable[[IdentityScope, Any], Awaitable[ToolResult]]


@dataclass(frozen=True)
class ToolSpec:
    """One registered tool. ``permission`` is documentation for the manifest; the handler
    rechecks it against the derived scope itself."""

    name: str
    description: str
    args_model: type[ToolArgs]
    permission: Permission
    handler: ToolHandler


@dataclass(frozen=True)
class RefusalEvent:
    """What the audit sink sees for a refused call: names and reasons only, never values."""

    tool: str
    reason: str
    key_names: tuple[str, ...]
    scope_hash: str


class RefusalSink(Protocol):
    def refused(self, event: RefusalEvent) -> None: ...


def _normalize(key: str) -> str:
    return re.sub(r"[-_\s]", "", key).lower()


def _safe_names(keys: list[str]) -> tuple[str, ...]:
    """Bounded, charset-restricted key names; anything odd is replaced, never echoed."""
    names = [k[:_MAX_KEY_LENGTH] if _SAFE_KEY.match(k) else "<unprintable>" for k in keys]
    return tuple(names[:_MAX_LOGGED_KEYS])


class ToolRegistry:
    """Holds the tools registered at construction. The set is immutable afterwards."""

    def __init__(self, specs: list[ToolSpec], *, sink: RefusalSink | None = None) -> None:
        names = [s.name for s in specs]
        if len(set(names)) != len(names):
            raise ValueError("duplicate tool name")
        self._specs: Mapping[str, ToolSpec] = {s.name: s for s in specs}
        self._sink = sink

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._specs))

    def manifest(self) -> tuple[ToolSpec, ...]:
        """The registered specs, sorted by name (for the model's tool list)."""
        return tuple(self._specs[n] for n in self.names)

    async def invoke(
        self, name: str, raw_args: Mapping[str, object], scope: IdentityScope
    ) -> ToolResult:
        spec = self._specs.get(name) if isinstance(name, str) else None
        if spec is None:
            self._refuse("<unregistered>", "tool_not_registered", [], scope)
            raise ToolNotRegisteredError

        keys = [str(k) for k in raw_args]
        scope_keys = [k for k in keys if _normalize(k) in SCOPE_SHAPED_KEYS]
        if scope_keys:
            self._refuse(spec.name, "scope_argument_refused", scope_keys, scope)
            raise ScopeArgumentRefusedError

        declared = set(spec.args_model.model_fields)
        extra = [k for k in keys if k not in declared]
        if extra:
            self._refuse(spec.name, "argument_not_allowed", extra, scope)
            raise ArgumentNotAllowedError

        try:
            args = spec.args_model.model_validate(dict(raw_args))
        except ValidationError as exc:
            raise _invalid_schema(exc) from None

        budget = args.requested_budget()
        timeout_ms = (
            DEFAULT_TIMEOUT_MS if budget is None else min(budget.timeout_ms, MAX_TIMEOUT_MS)
        )
        try:
            async with asyncio.timeout(timeout_ms / 1000):
                return await spec.handler(scope, args)
        except TimeoutError:
            raise ToolTimeoutError from None

    def _refuse(self, tool: str, reason: str, keys: list[str], scope: IdentityScope) -> None:
        names = _safe_names(keys)
        logger.warning(
            "copilot tool call refused",
            extra={
                "tool": tool,
                "reason": reason,
                "key_names": names,
                "scope_hash": scope.scope_hash,
            },
        )
        if self._sink is not None:
            self._sink.refused(
                RefusalEvent(tool=tool, reason=reason, key_names=names, scope_hash=scope.scope_hash)
            )


def _invalid_schema(exc: ValidationError) -> InvalidSchemaError:
    """Pointer + error type only: Pydantic messages can echo the offending value."""
    issues = [
        ValidationIssue("/" + "/".join(str(p) for p in e["loc"]), e["type"]) for e in exc.errors()
    ]
    return InvalidSchemaError(
        "tool arguments are invalid", errors=issues, reason="invalid_arguments"
    )
