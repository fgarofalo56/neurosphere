"""PRP-15 item 2: duplicate-agent candidates for consolidation REVIEW.

Advisory only. This package has no mutation path: it reads presented catalog relations
through ``GraphQuery`` and emits ``candidate_duplicate`` recommendations. Merging, deleting
or editing agents is never done here (and never automatically anywhere).
"""

from neurosphere_workers.recommendations.duplicates.config import (
    GENERATOR_ID,
    DuplicateConfig,
    SignalWeights,
)
from neurosphere_workers.recommendations.duplicates.detector import DuplicateDetector
from neurosphere_workers.recommendations.duplicates.models import (
    AgentLister,
    DuplicateCandidate,
    DuplicateRun,
    ReviewCandidate,
    SignalBreakdown,
    SimilaritySignalProvider,
)

__all__ = [
    "GENERATOR_ID",
    "AgentLister",
    "DuplicateCandidate",
    "DuplicateConfig",
    "DuplicateDetector",
    "DuplicateRun",
    "ReviewCandidate",
    "SignalBreakdown",
    "SignalWeights",
    "SimilaritySignalProvider",
]
