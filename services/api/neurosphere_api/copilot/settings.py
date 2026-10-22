"""Copilot orchestration budgets and the conversation retention policy (PRP-19 item 2).

Everything here is configuration, never derived from a request: a caller or a model cannot raise
a budget or pick a retention class. Retention is a named-class policy: each stored turn carries
its class and the ``expires_at`` computed from it (the Cosmos store also writes it as the
document ``ttl`` so the platform removes expired turns).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import timedelta
from types import MappingProxyType
from typing import Final

__all__ = [
    "DEFAULT_FILTER_KEYS",
    "DEFAULT_RETENTION",
    "CopilotSettings",
]

DEFAULT_FILTER_KEYS: Final = (
    "environment",
    "kind",
    "lifecycle_status",
    "model_name",
    "outcome",
    "provider",
    "status",
)
DEFAULT_RETENTION: Final[Mapping[str, timedelta]] = MappingProxyType(
    {"standard": timedelta(days=30), "short": timedelta(days=7)}
)


@dataclass(frozen=True, slots=True)
class CopilotSettings:
    """Server-side limits for one copilot turn and the retention policy for stored turns."""

    max_tool_iterations: int = 4
    """Model invocations per turn that may end in tool calls before the turn abstains."""
    max_tool_calls_per_iteration: int = 4
    max_output_tokens: int = 1024
    turn_timeout_seconds: float = 30.0
    max_text_chars: int = 4000
    """Longest accepted user message (and longest stored text)."""
    history_turns: int = 12
    """Most recent stored turns replayed to the model as conversation history."""
    max_selection: int = 20
    filter_keys: tuple[str, ...] = DEFAULT_FILTER_KEYS
    retention: Mapping[str, timedelta] = field(default_factory=lambda: dict(DEFAULT_RETENTION))
    default_retention_class: str = "standard"
    pseudonym_key: bytes | None = None
    """HMAC key (from the vault) for stable person pseudonyms; ``None`` uses a fixed marker."""
    protected_values: frozenset[str] = frozenset()
    """Exact secret values the server holds; a model answer containing one is blocked."""
    max_page_size: int = 50

    def __post_init__(self) -> None:
        if self.default_retention_class not in self.retention:
            raise ValueError("default_retention_class must be a configured retention class")
        if any(ttl <= timedelta(0) for ttl in self.retention.values()):
            raise ValueError("retention periods must be positive")
        if self.max_tool_iterations < 1 or self.max_tool_calls_per_iteration < 1:
            raise ValueError("tool budgets must be positive")
        if self.turn_timeout_seconds <= 0 or self.max_output_tokens < 1:
            raise ValueError("turn budgets must be positive")

    def ttl_for(self, retention_class: str) -> timedelta:
        return self.retention[retention_class]
