"""Deterministic detection and duplicate-precision measurement over generated sandbox data.

Not a test (no ``test_`` prefix, never collected). Reproduce the numbers in
``docs/evidence/G12/recommendations/README.md`` with::

    uv run python tests/integration/recommendations/measure_detection.py

Everything is synthetic and in-memory: fixed seeds, the sandbox generator, the SYNTHETIC sandbox
price snapshot, ``InMemoryRecommendationStore``. No network, no emulators, no wall clock.

Definitions (the same ones the evidence document states):

* an anomaly type is *detected* for an agent when the stored recommendation of the matching kind
  lists the agent as a subject and its ``evidence_status`` is ``sufficient`` (a cold-start record
  is a bounded "insufficient history" result, not a detection);
* ``insufficient_evidence`` counts labelled agents with a no-score insufficient-evidence record of
  the matching kind; it is neither a detection nor a false positive. ``insufficient_unlabelled``
  counts such records on unlabelled agents. ``silent_miss`` is labelled, not detected and without
  any record: it must be 0;
* a *false positive* is a detected agent that no manifest anomaly of ANY type names (a cost-spike
  agent that also trips the latency rule is a real effect, counted apart as ``cross_type``);
* duplicate precision and recall compare stored ``candidate_duplicate`` subject pairs with the
  manifest's ``duplicate_agent_candidates`` pairs.
"""

from __future__ import annotations

import asyncio
import json
import sys
import tempfile
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from neurosphere_core.recommendations import InMemoryRecommendationStore  # noqa: E402
from neurosphere_workers.recommendations.pipeline import (  # noqa: E402
    PipelineSummary,
    run_pipeline,
)
from neurosphere_workers.recommendations.tests.support import (  # noqa: E402
    CREATED_AT,
    PAIRS,
    generate_sandbox,
    make_scope,
    pilot_profile,
    synthetic_prices,
)

from sandbox.config import Profile  # noqa: E402

# manifest anomaly type -> recommendation kind
KINDS = {
    "cost_spike": "cost_spike",
    "latency_regression": "latency_degradation",
    "unused_agent": "unused_agent",
}


@dataclass(frozen=True)
class Setup:
    name: str
    profile: Profile
    seeds: tuple[int, ...]


def setups() -> list[Setup]:
    parity = pilot_profile()
    dense = pilot_profile(duplicate_pairs=3)
    sparse = replace(
        dense,
        name="custom",
        domains=8,
        agents=200,
        days=7,
        traces_per_agent_day=2.0,
        cost_spikes=5,
        latency_regressions=5,
        unused_agents=4,
        duplicate_pairs=4,
    )
    return [
        Setup(
            "dense-1dup (40 agents, 4 domains, 7 days, 20 traces/agent-day, 1 duplicate pair)",
            parity,
            (3, 11),
        ),
        Setup("dense (40 agents, 4 domains, 7 days, 20 traces/agent-day)", dense, (3, 11, 7, 5)),
        # Seed 5 is held out for the pilot density and the dense profile (never used to set a
        # threshold).
        Setup(
            "pilot density (200 agents, 8 domains, 7 days, 2 traces/agent-day)", sparse, (3, 11, 5)
        ),
    ]


async def measure(profile: Profile, seed: int) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="ns-measure-") as tmp:
        out = Path(tmp)
        generate_sandbox(out, seed=seed, profile=profile)
        domains = sorted(
            json.loads(line)["id"]
            for line in (out / "domains.ndjson").read_text(encoding="utf-8").splitlines()
            if line
        )
        scope = make_scope(domains)
        store = InMemoryRecommendationStore()
        summary: PipelineSummary = await run_pipeline(
            out,
            scope=scope,
            store=store,
            prices=synthetic_prices(),
            pairs=PAIRS,
            created_at=CREATED_AT,
        )
        manifest = json.loads((out / "anomaly-manifest.json").read_text(encoding="utf-8"))[
            "anomalies"
        ]
        stored = []
        for domain in domains:
            cursor = None
            while True:
                page = await store.list(scope, domain, cursor=cursor, limit=200)
                stored.extend(page.items)
                cursor = page.next_cursor
                if cursor is None:
                    break
    labelled = {a for an in manifest for a in an["affected_ids"]}
    result: dict[str, Any] = {"seed": seed, "stored": summary.stored, "types": {}}
    for anomaly_type, kind in KINDS.items():
        truth = {a for an in manifest if an["type"] == anomaly_type for a in an["affected_ids"]}
        detected = {
            s.root
            for r in stored
            if r.kind == kind and r.evidence_status == "sufficient"
            for s in r.subject_ids
        }
        insufficient = {
            s.root
            for r in stored
            if r.kind == kind and r.evidence_status == "insufficient_evidence"
            for s in r.subject_ids
        }
        result["types"][anomaly_type] = {
            "detected": len(truth & detected),
            "total": len(truth),
            "false_positives": len(detected - labelled),
            "cross_type": len((detected - truth) & labelled),
            # Reported apart: an insufficient-evidence record is neither a detection nor a false
            # positive. ``silent_miss`` = labelled, not detected, no insufficient-evidence record.
            "insufficient_evidence": len(truth & insufficient),
            "insufficient_unlabelled": len(insufficient - labelled),
            "silent_miss": len(truth - detected - insufficient),
            "missed": sorted(truth - detected - insufficient),
            "unlabelled_flags": sorted(detected - labelled),
        }
    truth_pairs = {
        frozenset(an["affected_ids"])
        for an in manifest
        if an["type"] == "duplicate_agent_candidates"
    }
    predicted = {
        frozenset(s.root for s in r.subject_ids) for r in stored if r.kind == "candidate_duplicate"
    }
    tp = len(truth_pairs & predicted)
    result["duplicates"] = {
        "predicted": len(predicted),
        "true_positive": tp,
        "labelled": len(truth_pairs),
        "precision": round(tp / len(predicted), 3) if predicted else None,
        "recall": round(tp / len(truth_pairs), 3) if truth_pairs else None,
        "review_candidates": len(summary.review_candidates),
    }
    result["projections"] = {
        "emitted": summary.counts_by_kind.get("model_right_sizing", 0),
        "skipped": len(summary.skipped_projections),
    }
    return result


async def main() -> None:
    for setup in setups():
        print(f"## {setup.name}")
        for seed in setup.seeds:
            print(json.dumps({"profile": setup.name, **await measure(setup.profile, seed)}))


if __name__ == "__main__":
    asyncio.run(main())
