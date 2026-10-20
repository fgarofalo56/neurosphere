"""The pre-call guard: runs for every selected item BEFORE any judge request exists.

Order (PRP-16 item 2): body fields, classification normalisation (null/unknown is restricted),
judge selection for the dimension, boundary cloud, capability-matrix availability, approval for
the classification, known price. The first failure skips the item with a reason code; the judge
is never called. This is the only place the decision is made; the service has no bypass.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from neurosphere_core.capabilities import CapabilityMatrix
from neurosphere_core.evaluation.registry import (
    Cloud,
    Dimension,
    JudgeConfig,
    judge_approval,
    judge_availability,
)
from neurosphere_core.payload import find_body_fields

from neurosphere_workers.evaluation.budget import price_known
from neurosphere_workers.evaluation.models import (
    REASON_BODY_FIELDS,
    REASON_JUDGE_CLOUD_MISMATCH,
    REASON_JUDGE_NOT_APPROVED,
    REASON_JUDGE_UNAVAILABLE,
    REASON_NO_JUDGE,
    REASON_PRICE_UNKNOWN,
    Candidate,
)

__all__ = ["GuardDecision", "check_candidate"]


@dataclass(frozen=True, slots=True)
class GuardDecision:
    config: JudgeConfig | None
    reason: str | None
    detail: str | None

    @property
    def allowed(self) -> bool:
        return self.config is not None and self.reason is None


def _skip(reason: str, detail: str) -> GuardDecision:
    return GuardDecision(None, reason, detail)


def check_candidate(
    candidate: Candidate,
    *,
    judges: Mapping[Dimension, JudgeConfig],
    matrix: CapabilityMatrix,
    cloud: Cloud,
    check_bodies: bool = True,
) -> GuardDecision:
    if check_bodies and (candidate.raw_body_fields or find_body_fields(candidate.payload)):
        return _skip(REASON_BODY_FIELDS, "prompt/response body fields present; never transmitted")
    effective = candidate.effective_classification  # null/unknown -> restricted
    config = judges.get(candidate.dimension)
    if config is None:
        return _skip(REASON_NO_JUDGE, f"no judge configured for {candidate.dimension}")
    if config.cloud != cloud:
        return _skip(
            REASON_JUDGE_CLOUD_MISMATCH,
            f"judge config cloud {config.cloud} does not match run cloud {cloud}",
        )
    available, why = judge_availability(config, matrix)
    if not available:
        return _skip(REASON_JUDGE_UNAVAILABLE, why)
    approved, why = judge_approval(config, candidate.classification, cloud)
    if not approved:
        return _skip(REASON_JUDGE_NOT_APPROVED, f"{why} (classification {effective})")
    if not price_known(config):
        return _skip(REASON_PRICE_UNKNOWN, "judge price unknown; cost cannot be bounded")
    return GuardDecision(config, None, None)
