"""The idle marker, in its own module so importing it pulls in nothing else.

``connector_config.stored`` imports the ``azure_monitor_ai`` settings, whose package imports the
poller, which imports ``sources_status``, which needs ``ConnectorIdle`` from this package. The
package ``__init__`` imports this module first so that chain never meets a half-built package.
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = ["ConnectorIdle"]


@dataclass(frozen=True, slots=True)
class ConnectorIdle:
    """The role must idle: its stored config is disabled (or source ``store`` has none)."""

    connector_kind: str
    reason: str
