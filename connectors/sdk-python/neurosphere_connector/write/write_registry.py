"""Action-target registration: only connectors with real write capability may be targets."""

from __future__ import annotations

import inspect

from neurosphere_core.errors import CapabilityUnavailableError

from neurosphere_connector.write.write_protocol import WriteConnector

__all__ = ["WriteTargetRegistry", "check_capable", "register_write_target"]


def _reject(reason: str, detail: str) -> CapabilityUnavailableError:
    return CapabilityUnavailableError(reason, detail)


def check_capable(connector: object) -> WriteConnector:
    """Return ``connector`` as a ``WriteConnector`` or raise ``CapabilityUnavailableError``.

    A connector missing a protocol member is refused with the member named in the detail.
    """
    try:
        return _check_members(connector)
    except AttributeError as exc:
        raise _reject(
            "write_protocol_not_implemented",
            f"connector lacks WriteConnector member {exc.name or 'unknown'}",
        ) from exc


def _check_members(connector: object) -> WriteConnector:
    if not isinstance(connector, WriteConnector):
        raise _reject(
            "write_protocol_not_implemented", "connector does not implement WriteConnector"
        )
    for method in ("dry_run", "apply", "verify", "rollback"):
        if not inspect.iscoroutinefunction(getattr(connector, method)):
            raise _reject(
                "write_protocol_not_implemented", f"WriteConnector.{method} must be an async def"
            )
    ws = connector.manifest.write_support
    if not ws.supported or not ws.actions:
        raise _reject("write_support_absent", "manifest declares no write support")
    if connector.advisory or connector.manifest.advisory:
        raise _reject("connector_advisory", "advisory connectors cannot back actions")
    return connector


# Kept until no caller uses the private name.
_check_capable = check_capable


class WriteTargetRegistry:
    """Connectors accepted as action targets, keyed by manifest name and optional target key.

    PRP-54: ``target_key`` (the intent's domain id) lets one registry hold several connectors
    of the same manifest name. A connector registered without a key is the default for every
    key that has no connector of its own. ``get(name)`` without a key stays valid while exactly
    one connector holds ``name``; with several it raises ``target_ambiguous``, never picks one.
    """

    def __init__(self) -> None:
        self._targets: dict[str, dict[str | None, WriteConnector]] = {}

    def register(self, connector: object, *, target_key: str | None = None) -> WriteConnector:
        """Validate and add ``connector``; raises ``CapabilityUnavailableError`` if not writable."""
        capable = check_capable(connector)
        self._targets.setdefault(capable.manifest.name, {})[target_key] = capable
        return capable

    def _find(self, name: str, target_key: str | None) -> WriteConnector | None:
        """The connector for ``name``/``target_key``; ``None`` when none; ambiguity raises."""
        held = self._targets.get(name)
        if not held:
            return None
        if target_key is not None:
            return held.get(target_key) or held.get(None)
        if len(held) == 1:
            return next(iter(held.values()))
        raise _reject("target_ambiguous", "several targets are registered; a target key is needed")

    def get(self, name: str, *, target_key: str | None = None) -> WriteConnector:
        found = self._find(name, target_key)
        if found is None:
            raise _reject("not_a_write_target", "no write target registered under that name")
        return found

    def supports(self, name: str, action: str, *, target_key: str | None = None) -> bool:
        try:
            target = self._find(name, target_key)
        except CapabilityUnavailableError:
            return False
        return target is not None and action in target.manifest.write_support.actions

    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._targets))

    def holds(self, name: str, target_key: str | None = None) -> bool:
        """True when a connector is registered under exactly ``name`` and ``target_key``."""
        return target_key in self._targets.get(name, {})

    def target_keys(self, name: str) -> tuple[str, ...]:
        """The target keys registered under ``name`` (the keyless default is not listed)."""
        return tuple(sorted(k for k in self._targets.get(name, {}) if k is not None))


def register_write_target(registry: WriteTargetRegistry, connector: object) -> WriteConnector:
    """Register ``connector`` in ``registry`` or raise ``CapabilityUnavailableError``."""
    return registry.register(connector)
