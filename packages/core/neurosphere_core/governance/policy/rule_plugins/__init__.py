"""Rule-evaluator plugins (PRP-105 clarification 14).

Each module here answers the rule kind it is named after and exposes
``build(ctx: RuleBuildContext) -> RuleEvaluator | None``; ``None`` means the kind is unavailable
in this deployment. ``RuleEvaluatorRegistry.discover(ctx)`` imports every module in name order.
PRP-105 ships this package empty; PRP-115 (``budget``), PRP-119 (``identity_entitlement``) and
PRP-130 (``required_attestation``) each add one module.
"""
