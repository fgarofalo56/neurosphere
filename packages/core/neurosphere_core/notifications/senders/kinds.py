"""Channel kind build status (PRP-107 item 4; verdicts in docs/connectors/verification).

``webhook`` is buildable, ``teams_webhook`` is degraded (Workflows exists in Commercial and GCC
only) and ``email`` is not built (no verified transport). Anything else is ``not_built``.
"""

from __future__ import annotations

from typing import Final, Literal

__all__ = [
    "KIND_STATUS",
    "KindNotBuildableError",
    "KindStatus",
    "kind_status",
    "require_buildable",
]

KindStatus = Literal["buildable", "degraded", "not_built"]

KIND_STATUS: Final[dict[str, tuple[KindStatus, str | None]]] = {
    "webhook": ("buildable", None),
    "teams_webhook": ("degraded", "teams_workflows_commercial_and_gcc_only"),
    "email": ("not_built", "email_transport_not_built"),
}

_UNKNOWN: Final[tuple[KindStatus, str]] = ("not_built", "unknown_channel_kind")


class KindNotBuildableError(Exception):
    """The channel kind has no sender. ``reason`` is a stable machine code."""

    def __init__(self, kind: str, reason: str) -> None:
        self.kind = kind
        self.reason = reason
        super().__init__(f"channel kind is not built: {reason}")


def kind_status(kind: str) -> tuple[KindStatus, str | None]:
    return KIND_STATUS.get(kind, _UNKNOWN)


def require_buildable(kind: str) -> tuple[KindStatus, str | None]:
    """Return ``(status, reason)`` for a kind that has a sender; raise for ``not_built``."""
    status, reason = kind_status(kind)
    if status == "not_built":
        raise KindNotBuildableError(kind, reason or "unknown_channel_kind")
    return status, reason
