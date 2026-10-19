"""Model right-sizing candidates with a priced, uncertain, advisory estimate (PRP-15 item 3).

What this is: given a usage summary and a configured candidate pair, price the SAME observed
tokens at the current model and at the candidate model from one versioned price snapshot and emit
a PRP-01 ``Recommendation`` of kind ``model_right_sizing``. It is a candidate list entry, not a
swap and not a claim of savings: ``projected_estimate`` is an estimate that cites the price
version, and every compatibility, quality, rollout and rollback prerequisite is open.

Decisions (also asserted by tests):

* ``method="rule"``, ``evidence_status="insufficient_evidence"``, no ``score``. Nothing here
  measures whether the candidate is as good as the current model, so there is no honest
  confidence score to report; the schema then requires ``insufficient_evidence``.
* Uncertainty is ``rule_bound`` over the point estimate. ``uncertainty.lower`` and ``.upper`` are
  multipliers on ``projected_amount``: ``1 - band`` and ``(1 + band) / observed_fraction``. The
  band is the config's relative token-volume uncertainty; dividing by the observed fraction
  widens the upper bound for tokens the evidence did not observe. ``lower_amount`` and
  ``upper_amount`` are the same multipliers applied to the amount. With unknown or zero observed
  fraction no bound is defensible, so the uncertainty is ``not_estimable`` and carries no bounds.
* Pricing date is the last instant inside the evidence window (the window is half-open).
* Both prices must come from ONE snapshot (the one resolved for the current model); a candidate
  absent from that snapshot is unresolved. No mixing of price versions, so ``cost_comparison`` is
  ``met`` for every emitted record and its evidence id is the snapshot id.
* No resolvable price -> ``InvalidSchemaError(reason="price_unresolved")``, nothing emitted.
  Unknown tokens, or tokens the sheet cannot price (cached tokens with no cached rate) -> ``None``.
* Government uses the same path; only a snapshot that lists ``government`` can price it.
* The record id's kind segment uses hyphens (``model-right-sizing``) because the canonical-id
  grammar for the last segment has no underscore.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from neurosphere_contracts.recommendations.v1.recommendation import Recommendation
from neurosphere_core.errors import InvalidSchemaError
from neurosphere_core.ledger.models import quantize
from neurosphere_core.ledger.prices import PriceTable
from neurosphere_core.pricing import PriceSnapshot, PriceSnapshotStore

from neurosphere_workers.recommendations.projection.models import (
    CandidatePair,
    CandidatePairConfig,
    UsageSummary,
)

KIND = "model_right_sizing"
SCHEMA_VERSION = "1.0.0"
GENERATOR_PREFIX = "projection.right-sizing"
PRICE_UNRESOLVED = "price_unresolved"
TOKENS_UNKNOWN = "tokens_unknown"


@dataclass(frozen=True, slots=True)
class CostComparison:
    """Same observed tokens priced at two models from one snapshot (``Decimal`` money)."""

    snapshot: PriceSnapshot
    currency: str
    baseline_amount: Decimal
    projected_amount: Decimal


@dataclass(frozen=True, slots=True)
class SkippedProjection:
    agent_id: str
    pair_id: str
    reason: str


@dataclass(frozen=True, slots=True)
class ProjectionBatch:
    recommendations: tuple[Recommendation, ...]
    skipped: tuple[SkippedProjection, ...]


def _ts(value: datetime) -> str:
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def price_date(usage: UsageSummary) -> date:
    """The last day touched by the (half-open) evidence window."""
    return (usage.window_end - timedelta(microseconds=1)).astimezone(UTC).date()


def recommendation_id(
    *,
    cloud: str,
    customer_id: str,
    kind: str,
    generator_id: str,
    generator_version: str,
    subject_ids: list[str],
    window_start: str,
    window_end: str,
) -> str:
    """``{cloud}:{customer_id}:neurosphere:recommendation:{kind}-{h}`` (shared convention)."""
    material = "|".join(
        [generator_id, generator_version, *sorted(subject_ids), window_start, window_end]
    )
    digest = hashlib.sha256(material.encode("utf-8")).hexdigest()[:24]
    slug = kind.replace("_", "-")
    return f"{cloud}:{customer_id}:neurosphere:recommendation:{slug}-{digest}"


def compare_model_costs(
    usage: UsageSummary, pair: CandidatePair, store: PriceSnapshotStore
) -> CostComparison | None:
    """Price the observed tokens at the current and candidate model.

    Returns ``None`` when the tokens are unknown or cannot be priced; raises ``InvalidSchemaError``
    (reason ``price_unresolved``) when no price version resolves for the cloud and date.
    """
    on = price_date(usage)
    baseline = store.resolve_token_price(
        usage.cloud, usage.provider, usage.current_model, usage.current_model_version, on
    )
    if baseline is None:
        raise InvalidSchemaError(
            f"no price version resolves for {usage.current_model} in {usage.cloud} on {on}",
            reason=PRICE_UNRESOLVED,
        )
    candidate_provider = pair.candidate_provider or pair.provider
    candidate_rate = baseline.version.rate_for(
        candidate_provider, pair.candidate_model, pair.candidate_model_version
    )
    if candidate_rate is None:
        raise InvalidSchemaError(
            f"price version {baseline.version.price_version_id} has no rate for "
            f"{pair.candidate_model}",
            reason=PRICE_UNRESOLVED,
        )
    tokens = usage.tokens
    if tokens.input is None or tokens.output is None:
        return None
    table = PriceTable([baseline.version])
    current = table.estimate_cost(
        usage.provider, usage.current_model, usage.current_model_version, tokens, on
    )
    candidate = table.estimate_cost(
        candidate_provider, pair.candidate_model, pair.candidate_model_version, tokens, on
    )
    if current.amount is None or candidate.amount is None:
        return None
    return CostComparison(
        snapshot=baseline.snapshot,
        currency=baseline.version.currency,
        baseline_amount=current.amount,
        projected_amount=candidate.amount,
    )


def _fmt(value: Decimal) -> str:
    return format(quantize(value), "f")


def project_right_sizing(
    usage: UsageSummary,
    pair: CandidatePair,
    config: CandidatePairConfig,
    store: PriceSnapshotStore,
    *,
    created_at: datetime,
) -> Recommendation | None:
    """Emit one ``model_right_sizing`` recommendation, or ``None`` when tokens are unknown or
    unpriceable. Raises ``InvalidSchemaError`` when no price version resolves."""
    comparison = compare_model_costs(usage, pair, store)
    if comparison is None:
        return None
    if created_at.tzinfo is None:
        raise InvalidSchemaError("created_at has no timezone", reason="created_at")

    subjects = [usage.agent_id]
    if usage.deployment_id is not None:
        subjects.append(usage.deployment_id)
    start, end = _ts(usage.window_start), _ts(usage.window_end)
    generator_id = f"{GENERATOR_PREFIX}.{config.config_id}.{pair.pair_id}"
    snapshot = comparison.snapshot

    fraction = usage.observed_fraction
    estimate: dict[str, object] = {
        "estimate_kind": "estimated",
        "period": "evidence_window",
        "baseline_amount": _fmt(comparison.baseline_amount),
        "projected_amount": _fmt(comparison.projected_amount),
        "currency": comparison.currency,
        "price_version": snapshot.snapshot_id,
        "price_effective_date": snapshot.effective_date.isoformat(),
    }
    uncertainty: dict[str, object]
    if fraction is not None and fraction > 0:
        low_mult = Decimal(1) - config.volume_band
        high_mult = (Decimal(1) + config.volume_band) / Decimal(str(fraction))
        estimate["lower_amount"] = _fmt(comparison.projected_amount * low_mult)
        estimate["upper_amount"] = _fmt(comparison.projected_amount * high_mult)
        uncertainty = {
            "method": "rule_bound",
            "lower": float(low_mult),
            "upper": float(high_mult),
        }
    else:
        uncertainty = {"method": "not_estimable"}

    coverage: dict[str, object] = {
        "method": usage.coverage_method,
        "observed_fraction": fraction,
    }
    if usage.missing_source_ids:
        coverage["missing_source_ids"] = list(usage.missing_source_ids)

    prerequisites: list[dict[str, object]] = [
        {"kind": kind, "status": "unknown"}
        for kind in (
            "capability_compatibility",
            "context_compatibility",
            "tool_compatibility",
            "quality_regression_test",
            "staged_rollout_plan",
            "rollback_plan",
        )
    ]
    prerequisites.append(
        {"kind": "cost_comparison", "status": "met", "evidence_ids": [snapshot.snapshot_id]}
    )

    owner: dict[str, object] = (
        {"resolution": "assigned", "owner_id": usage.owner_id}
        if usage.owner_id is not None
        else {"resolution": "unresolved", "owner_id": None}
    )

    document: dict[str, object] = {
        "schema_version": SCHEMA_VERSION,
        "recommendation_id": recommendation_id(
            cloud=usage.cloud,
            customer_id=usage.customer_id,
            kind=KIND,
            generator_id=generator_id,
            generator_version=config.version,
            subject_ids=subjects,
            window_start=start,
            window_end=end,
        ),
        "cloud": usage.cloud,
        "customer_id": usage.customer_id,
        "domain_id": usage.domain_id,
        "kind": KIND,
        "subject_ids": subjects,
        "method": "rule",
        "generator": {"generator_id": generator_id, "generator_version": config.version},
        "evidence_status": "insufficient_evidence",
        "evidence_window": {"start": start, "end": end},
        "evidence_ids": list(usage.evidence_ids),
        "coverage": coverage,
        "uncertainty": uncertainty,
        "prerequisites": prerequisites,
        "projected_estimate": estimate,
        "owner": owner,
        "advisory": True,
        "created_at": _ts(created_at),
    }
    return Recommendation.model_validate(document)


def project_right_sizing_candidates(
    usages: list[UsageSummary],
    config: CandidatePairConfig,
    store: PriceSnapshotStore,
    *,
    created_at: datetime,
) -> ProjectionBatch:
    """Run every configured pair that matches each usage summary. A pair that cannot be priced is
    recorded in ``skipped`` with its reason; nothing is emitted for it."""
    emitted: list[Recommendation] = []
    skipped: list[SkippedProjection] = []
    for usage in usages:
        for pair in config.pairs_for(usage):
            try:
                record = project_right_sizing(usage, pair, config, store, created_at=created_at)
            except InvalidSchemaError as error:
                skipped.append(
                    SkippedProjection(
                        usage.agent_id, pair.pair_id, error.reason or "invalid_schema"
                    )
                )
                continue
            if record is None:
                skipped.append(SkippedProjection(usage.agent_id, pair.pair_id, TOKENS_UNKNOWN))
            else:
                emitted.append(record)
    return ProjectionBatch(tuple(emitted), tuple(skipped))
