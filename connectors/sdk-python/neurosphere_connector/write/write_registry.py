"""Action-target registration: only connectors with real write capability may be targets."""

from __future__ import annotations

from neurosphere_core.errors import CapabilityUnavailableError

from neurosphere_connector.write.write_protocol import WriteConnector

__all__ = ["WriteTargetRegistry", "register_write_target"]


def _reject(reason: str, detail: str) -> CapabilityUnavailableError:
    return CapabilityUnavailableError(reason, detail)


def _check_capable(connector: object) -> WriteConnector:
    if not isinstance(connector, WriteConnector):
        raise _reject(
            "write_protocol_not_implemented", "connector does not implement WriteConnector"
        )
    ws = connector.manifest.write_support
    if not ws.supported or not ws.actions:
        raise _reject("write_support_absent", "manifest declares no write support")
    if connector.advisory or connector.manifest.advisory:
        raise _reject("connector_advisory", "advisory connectors cannot back actions")
    return connector


class WriteTargetRegistry:
    """Connectors accepted as action targets, keyed by manifest name."""

    def __init__(self) -> None:
        self._targets: dict[str, WriteConnector] = {}

    def register(self, connector: object) -> WriteConnector:
        """Validate and add ``connector``; raises ``CapabilityUnavailableError`` if not writable."""
        capable = _check_capable(connector)
        self._targets[capable.manifest.name] = capable
        return capable

    def get(self, name: str) -> WriteConnector:
        try:
            return self._targets[name]
        except KeyError:
            raise _reject(
                "not_a_write_target", "no write target registered under that name"
            ) from None

    def supports(self, name: str, action: str) -> bool:
        target = self._targets.get(name)
        return target is not None and action in target.manifest.write_support.actions

    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._targets))


def register_write_target(registry: WriteTargetRegistry, connector: object) -> WriteConnector:
    """Register ``connector`` in ``registry`` or raise ``CapabilityUnavailableError``."""
    return registry.register(connector)
