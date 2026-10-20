"""Stratified sampling over (domain, agent, classification) (PRP-16 item 2).

Deterministic: duplicates are dropped (first by item id), strata and ids are sorted, and a single
``random.Random(seed)`` is consumed in sorted-stratum order, so the same seed over the same
population always yields the same sample. Each stratum gets ``ceil(rate * population)`` items (at
least one), and the selected items are interleaved round-robin across strata so a run that stops
early (budget) still covers every stratum evenly. Coverage per stratum is reported, never implied.
"""

from __future__ import annotations

import math
import random
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass

from neurosphere_core.errors import InvalidSchemaError

from neurosphere_workers.evaluation.models import Candidate

__all__ = ["SampleResult", "StratumSample", "stratified_sample"]


@dataclass(frozen=True, slots=True)
class StratumSample:
    stratum: str
    population: int
    sampled: int

    @property
    def fraction(self) -> float | None:
        return (self.sampled / self.population) if self.population else None


@dataclass(frozen=True, slots=True)
class SampleResult:
    selected: tuple[Candidate, ...]  # round-robin order across strata
    strata: tuple[StratumSample, ...]  # sorted by stratum label


def stratified_sample(candidates: Sequence[Candidate], *, rate: float, seed: int) -> SampleResult:
    if not 0.0 < rate <= 1.0:
        raise InvalidSchemaError("sampling rate must be in (0, 1]", reason="invalid_rate")
    unique: dict[str, Candidate] = {}
    for cand in sorted(candidates, key=lambda c: c.item_id):
        unique.setdefault(cand.item_id, cand)
    by_stratum: dict[str, list[Candidate]] = defaultdict(list)
    for cand in unique.values():
        by_stratum[cand.stratum].append(cand)

    rng = random.Random(seed)  # noqa: S311 - reproducible sampling, not security
    chosen: dict[str, list[Candidate]] = {}
    summary: list[StratumSample] = []
    for stratum in sorted(by_stratum):
        members = by_stratum[stratum]  # already item-id sorted
        count = min(len(members), max(1, math.ceil(rate * len(members) - 1e-9)))
        chosen[stratum] = rng.sample(members, count)
        summary.append(StratumSample(stratum, len(members), count))

    order: list[Candidate] = []
    depth = max((len(v) for v in chosen.values()), default=0)
    for level in range(depth):
        for stratum in sorted(chosen):
            if level < len(chosen[stratum]):
                order.append(chosen[stratum][level])
    return SampleResult(tuple(order), tuple(summary))
