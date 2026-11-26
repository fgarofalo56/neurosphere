"""``RuleEvaluatorRegistry`` and the rule-plugin extension point (PRP-105 clarification 14).

``discover(ctx)`` imports every module of the plugin package (by default
``neurosphere_core.governance.policy.rule_plugins``) found by ``pkgutil.iter_modules``, in name
order, and calls its ``build(ctx: RuleBuildContext) -> RuleEvaluator | None``. The module name is
the rule kind it answers. ``None`` means the kind is unavailable in this deployment; a module
that fails to import, has no ``build``, raises from it, returns something that is not an
evaluator, or answers a kind that is already registered is reported unavailable with reason
``plugin_failed``. Discovery never raises: a broken plugin cannot stop the worker or the API.

A later rule kind (PRP-115 ``budget``, PRP-119 ``identity_entitlement``, PRP-130
``required_attestation``) adds one module ``rule_plugins/<kind>.py`` and edits nothing here.
"""

from __future__ import annotations

import importlib
import logging
import pkgutil
from typing import Final, Literal

from pydantic import BaseModel, ConfigDict

from neurosphere_core.governance.policy.rules.base import RuleBuildContext, RuleEvaluator

__all__ = [
    "PLUGIN_PACKAGE",
    "EvaluatorStatus",
    "RuleEvaluatorRegistry",
    "UnavailableKind",
    "UnavailableReason",
]

PLUGIN_PACKAGE: Final = "neurosphere_core.governance.policy.rule_plugins"

UnavailableReason = Literal[
    "plugin_failed",
    "unavailable_in_deployment",
    "finding_reader_unbound",
    "no_evaluator",
]
EvaluatorStatus = Literal["available", "evaluator_unavailable"]

_log = logging.getLogger(__name__)


class UnavailableKind(BaseModel):
    """A rule kind with no evaluator in this deployment, and why (a reason code, no text)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: str
    reason: UnavailableReason
    module: str | None = None
    """Plugin module that reported it, when it came from discovery."""


class RuleEvaluatorRegistry:
    """Rule kind -> evaluator, plus the kinds known to be unavailable and why."""

    def __init__(self, *, plugin_package: str = PLUGIN_PACKAGE) -> None:
        self._plugin_package = plugin_package
        self._evaluators: dict[str, RuleEvaluator] = {}
        self._unavailable: dict[str, UnavailableKind] = {}

    def register(self, evaluator: RuleEvaluator) -> None:
        """Add an evaluator. Raises ``ValueError`` when its kind already has one."""
        kind = evaluator.kind
        if kind in self._evaluators:
            raise ValueError(f"duplicate rule evaluator for kind {kind}")
        self._evaluators[kind] = evaluator
        self._unavailable.pop(kind, None)

    def mark_unavailable(
        self, kind: str, reason: UnavailableReason, *, module: str | None = None
    ) -> None:
        """Record that ``kind`` has no evaluator here (ignored when one is registered)."""
        if kind not in self._evaluators:
            self._unavailable[kind] = UnavailableKind(kind=kind, reason=reason, module=module)

    def get(self, kind: str) -> RuleEvaluator | None:
        return self._evaluators.get(kind)

    def __contains__(self, kind: object) -> bool:
        return kind in self._evaluators

    @property
    def available_kinds(self) -> tuple[str, ...]:
        return tuple(sorted(self._evaluators))

    @property
    def unavailable_kinds(self) -> tuple[UnavailableKind, ...]:
        return tuple(self._unavailable[k] for k in sorted(self._unavailable))

    def status(self, kind: str) -> EvaluatorStatus:
        return "available" if kind in self._evaluators else "evaluator_unavailable"

    def unavailable_reason(self, kind: str) -> UnavailableReason | None:
        """Why ``kind`` cannot be evaluated; ``no_evaluator`` for a kind nobody reported."""
        if kind in self._evaluators:
            return None
        held = self._unavailable.get(kind)
        return held.reason if held is not None else "no_evaluator"

    def discover(self, ctx: RuleBuildContext) -> tuple[str, ...]:
        """Load every plugin module; return the kinds registered by this call."""
        try:
            package = importlib.import_module(self._plugin_package)
        except Exception:
            _log.warning("rule_plugin_package_unavailable package=%s", self._plugin_package)
            return ()
        paths = getattr(package, "__path__", None)
        if paths is None:
            return ()
        names = sorted(
            info.name
            for info in pkgutil.iter_modules(paths)
            if not info.ispkg and not info.name.startswith("_")
        )
        added: list[str] = []
        for name in names:
            kind = self._load(name, ctx)
            if kind is not None:
                added.append(kind)
        return tuple(added)

    def _load(self, name: str, ctx: RuleBuildContext) -> str | None:
        module_name = f"{self._plugin_package}.{name}"
        try:
            module = importlib.import_module(module_name)
            build = getattr(module, "build", None)
            if not callable(build):
                raise TypeError("plugin has no build(ctx)")
            evaluator = build(ctx)
            if evaluator is None:
                self.mark_unavailable(name, "unavailable_in_deployment", module=module_name)
                return None
            if not isinstance(evaluator, RuleEvaluator):
                raise TypeError("build(ctx) did not return a RuleEvaluator")
            self.register(evaluator)
        except Exception as exc:
            _log.warning("rule_plugin_failed module=%s error=%s", module_name, type(exc).__name__)
            self.mark_unavailable(name, "plugin_failed", module=module_name)
            return None
        return evaluator.kind
