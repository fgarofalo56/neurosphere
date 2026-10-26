"""The ``composition`` readiness probe (PRP-29 wire contract "Readiness").

``/readyz`` keeps its body shape, ``{"status": ..., "dependencies": {name: reason_code}}`` with
the health module's reason codes (``ok``/``timeout``/``connection_refused``/``unavailable``).
The health router reads ``app.state.health_probes``; composition sets it to a live view of:

* the environment probes (``probes_from_env``: ``cosmos``, ``eventhubs``, ``blob``);
* ``composition``: ``ok`` when no component blocks readiness, else ``unavailable``;
* one detail entry per component that is not ``ok``, named
  ``composition.<component>.<code>`` where ``<code>`` is the state (``not_built``,
  ``disabled``) or the failure reason code (``tenant_id_missing``, ``cosmos_unconfigured``...).
  Its value is ``unavailable`` when that component blocks readiness and ``ok`` when it does not
  (an optional component that is ``disabled``).

Only component names and enumerated reason codes appear; never a configuration value.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from typing import Final

from fastapi import FastAPI

from neurosphere_api.health.probes import DependencyProbe, ReasonCode
from neurosphere_api.runtime.status import ComponentRegistry, ComponentStatus

__all__ = [
    "COMPOSITION_PROBE",
    "CompositionProbe",
    "ReadinessProbes",
    "detail_name",
    "install_readiness",
]

COMPOSITION_PROBE: Final = "composition"


def detail_name(status: ComponentStatus) -> str:
    return f"{COMPOSITION_PROBE}.{status.name}.{status.code}"


class CompositionProbe:
    """``ok`` exactly when no required component (or failed optional one) blocks readiness."""

    def __init__(self, registry: ComponentRegistry) -> None:
        self.name = COMPOSITION_PROBE
        self._registry = registry

    async def check(self) -> ReasonCode:
        return "ok" if self._registry.ready else "unavailable"


class _DetailProbe:
    def __init__(self, status: ComponentStatus) -> None:
        self.name = detail_name(status)
        self._code: ReasonCode = "unavailable" if status.blocks_readiness else "ok"

    async def check(self) -> ReasonCode:
        return self._code


class ReadinessProbes:
    """Iterable probe set; detail entries are recomputed on every ``/readyz`` call."""

    def __init__(self, env_probes: Sequence[DependencyProbe], registry: ComponentRegistry) -> None:
        self._env = tuple(env_probes)
        self._registry = registry
        self._composition = CompositionProbe(registry)

    def __iter__(self) -> Iterator[DependencyProbe]:
        yield from self._env
        yield self._composition
        for status in self._registry.snapshot():
            if status.state != "ok":
                yield _DetailProbe(status)


def install_readiness(
    app: FastAPI, registry: ComponentRegistry, env_probes: Sequence[DependencyProbe]
) -> ReadinessProbes:
    probes = ReadinessProbes(env_probes, registry)
    app.state.health_probes = probes
    return probes
