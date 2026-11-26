"""Registration of the seven rule kinds PRP-105 evaluates, then plugin discovery (item 2).

``content_rule`` is registered only when an ``InteractionFindingReader`` is bound; otherwise it
is reported unavailable with reason ``finding_reader_unbound``. The worker assembly and the API
builder both call :func:`build_rule_registry`, so both see the same available kinds.
"""

from __future__ import annotations

from typing import Final

from neurosphere_core.governance.policy.rules.base import RuleBuildContext
from neurosphere_core.governance.policy.rules.content_rule import ContentRuleEvaluator
from neurosphere_core.governance.policy.rules.data_sensitivity_access import (
    DataSensitivityAccessEvaluator,
)
from neurosphere_core.governance.policy.rules.findings_port import InteractionFindingReader
from neurosphere_core.governance.policy.rules.model_allow_list import ModelAllowListEvaluator
from neurosphere_core.governance.policy.rules.registration_required import (
    RegistrationRequiredEvaluator,
)
from neurosphere_core.governance.policy.rules.registry import PLUGIN_PACKAGE, RuleEvaluatorRegistry
from neurosphere_core.governance.policy.rules.required_approval import RequiredApprovalEvaluator
from neurosphere_core.governance.policy.rules.required_owner import RequiredOwnerEvaluator
from neurosphere_core.governance.policy.rules.residency import ResidencyEvaluator

__all__ = ["BUILTIN_KINDS", "build_rule_registry", "register_builtin_evaluators"]

BUILTIN_KINDS: Final = (
    "model_allow_list",
    "data_sensitivity_access",
    "residency",
    "required_owner",
    "required_approval",
    "registration_required",
    "content_rule",
)
"""The seven kinds this PRP evaluates (clarification 2)."""


def register_builtin_evaluators(
    registry: RuleEvaluatorRegistry,
    ctx: RuleBuildContext,
    *,
    finding_reader: InteractionFindingReader | None = None,
) -> RuleEvaluatorRegistry:
    """Register the builtin evaluators on ``registry``, then ``registry.discover(ctx)``."""
    registry.register(ModelAllowListEvaluator(ctx.catalog, ctx.metrics))
    registry.register(DataSensitivityAccessEvaluator(ctx.catalog, ctx.access))
    registry.register(ResidencyEvaluator(ctx.catalog))
    registry.register(RequiredOwnerEvaluator(ctx.catalog))
    registry.register(RequiredApprovalEvaluator(ctx.catalog))
    registry.register(RegistrationRequiredEvaluator(ctx.catalog, ctx.metrics))
    if finding_reader is not None:
        registry.register(ContentRuleEvaluator(finding_reader))
    else:
        registry.mark_unavailable("content_rule", "finding_reader_unbound")
    registry.discover(ctx)
    return registry


def build_rule_registry(
    ctx: RuleBuildContext,
    *,
    finding_reader: InteractionFindingReader | None = None,
    plugin_package: str = PLUGIN_PACKAGE,
) -> RuleEvaluatorRegistry:
    """A new registry with the builtin evaluators and every discovered plugin."""
    return register_builtin_evaluators(
        RuleEvaluatorRegistry(plugin_package=plugin_package), ctx, finding_reader=finding_reader
    )
