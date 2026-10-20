"""Cost projections for right-sizing candidates (PRP-15 item 3). Advisory; no swap or savings claim.

Entry points: ``project_right_sizing`` (one usage x one pair), ``project_right_sizing_candidates``
(batch over a versioned pair config) and ``compare_model_costs``.
"""

from neurosphere_workers.recommendations.projection.models import (
    CandidatePair,
    CandidatePairConfig,
    UsageSummary,
)
from neurosphere_workers.recommendations.projection.right_sizing import (
    CostComparison,
    ProjectionBatch,
    SkippedProjection,
    compare_model_costs,
    project_right_sizing,
    project_right_sizing_candidates,
    recommendation_id,
)

__all__ = [
    "CandidatePair",
    "CandidatePairConfig",
    "CostComparison",
    "ProjectionBatch",
    "SkippedProjection",
    "UsageSummary",
    "compare_model_costs",
    "project_right_sizing",
    "project_right_sizing_candidates",
    "recommendation_id",
]
