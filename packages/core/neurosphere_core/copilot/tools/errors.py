"""Typed refusals of the copilot tool registry, all members of the PRP-01 error taxonomy.

Details never carry argument values: a refused model argument may hold anything, including
injected instructions, so only names and fixed reasons reach an error body or a log line.
"""

from __future__ import annotations

from neurosphere_core.errors import (
    DependencyTransientError,
    ForbiddenError,
    InvalidSchemaError,
)

__all__ = [
    "ArgumentNotAllowedError",
    "ScopeArgumentRefusedError",
    "ToolBudgetError",
    "ToolNotRegisteredError",
    "ToolPermissionError",
    "ToolTimeoutError",
]


class ToolNotRegisteredError(ForbiddenError):
    """The model named a tool that is not on the allowlist. Nothing is looked up or invoked."""

    def __init__(self) -> None:
        super().__init__("tool is not registered", reason="tool_not_registered")


class ScopeArgumentRefusedError(ForbiddenError):
    """A scope-shaped argument was supplied. The value is never consulted; the call is refused."""

    def __init__(self) -> None:
        super().__init__(
            "scope is derived by the server and cannot be supplied", reason="scope_argument_refused"
        )


class ArgumentNotAllowedError(ForbiddenError):
    """The call carried an argument the tool does not declare."""

    def __init__(self) -> None:
        super().__init__("argument is not allowed for this tool", reason="argument_not_allowed")


class ToolPermissionError(ForbiddenError):
    """The derived scope lacks the permission the tool needs on any domain."""

    def __init__(self, permission: str) -> None:
        super().__init__(f"{permission} is not held on any domain", reason="permission_denied")


class ToolBudgetError(InvalidSchemaError):
    """The structured query asks for something the tool budget or operation set does not allow."""

    def __init__(self, detail: str, *, reason: str = "budget_denied") -> None:
        super().__init__(detail, reason=reason)


class ToolTimeoutError(DependencyTransientError):
    """The tool exceeded its wall-clock budget."""

    def __init__(self) -> None:
        super().__init__("tool exceeded its time budget", reason="tool_timeout")
