"""Measure the PRP-16 pilot pipeline over SYNTHETIC sandbox data and print the numbers.

Not a test (no ``test_`` prefix, never collected). Reproduce the numbers in
``docs/evidence/G12/evaluation/README.md`` with::

    uv run python tests/integration/evaluation/measure.py

Everything is synthetic and in memory: the committed sandbox benchmark data, recorded judge
fixtures, ``InMemoryEvaluationStore``, the SHIPPED capability matrix. No network, no cloud, no
paid call, no wall clock.
"""

from __future__ import annotations

import asyncio
import json
import sys
import tempfile
from decimal import Decimal
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parents[3]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from neurosphere_core.evaluation.calibration import calibrate  # noqa: E402
from neurosphere_core.evaluation.registry import judge_availability  # noqa: E402
from neurosphere_workers.evaluation.budget import BudgetLimits  # noqa: E402
from neurosphere_workers.evaluation.models import RunReport  # noqa: E402
from neurosphere_workers.evaluation.service import EvaluationService  # noqa: E402
from neurosphere_workers.evaluation.source import NdjsonRecordSource  # noqa: E402

from tests.integration.evaluation import support as sp  # noqa: E402


def _coverage(report: RunReport) -> list[dict[str, Any]]:
    return [
        {
            "stratum": c.stratum,
            "population": c.population,
            "evaluated": c.evaluated,
            "skipped": c.skipped,
        }
        for c in report.coverage
    ]


async def main() -> None:
    out: dict[str, Any] = {}

    s = await sp.run_slice()
    off = s.summary.offline
    result = off.results[0]
    score = result.scores[0]
    cal = s.summary.calibrations[0]
    labels = sp.sandbox_label_set()
    accuracy = calibrate(
        [j for j in off.judged_items if j.dimension == "groundedness"],
        labels,
        dimension="groundedness",
        label_set_version=labels.label_set_version,
        metric="accuracy",
        calibration_ref="measure-accuracy",
        calibrated_at=sp.NOW,
    )
    out["pilot_gov"] = {
        "dataset": f"{off.dataset_id}@{off.dataset_version}",
        "items": off.population_total,
        "status": off.status,
        "skip_counts": off.skip_counts,
        "judge_calls": s.fixture.call_count,
        "scored": score.sample_size,
        "abstained": sum(1 for o in off.outcomes if o.status == "abstained"),
        "rate": score.value,
        "wilson_95": [score.uncertainty.lower, score.uncertainty.upper],
        "calibration_cohen_kappa": {
            "agreement": cal.agreement,
            "pairs": cal.agreement_sample_size,
            "interval": [cal.agreement_interval.lower, cal.agreement_interval.upper],
            "method": cal.agreement_interval.method,
            "bias_mean_diff": cal.bias.mean_difference,
        },
        "calibration_accuracy": {
            "agreement": accuracy.agreement,
            "interval": [accuracy.agreement_interval.lower, accuracy.agreement_interval.upper],
        },
        "coverage": _coverage(off),
        "usage": [
            {
                "calls": u.calls,
                "input_tokens": u.input_tokens,
                "output_tokens": u.output_tokens,
                "estimated_cost_usd": str(u.estimated_cost),
                "price_version": u.price_version,
            }
            for u in off.usage
        ],
        "drift": [
            {
                "state": d.state,
                "psi": d.statistic,
                "baseline_n": d.baseline_n,
                "current_n": d.current_n,
            }
            for d in s.summary.drift
        ],
        "stored": {
            "results": s.summary.results_stored,
            "calibrations": s.summary.calibrations_stored,
            "coverage_rows": s.summary.coverage_stored,
            "drift_alerts": s.summary.drift_alerts_stored,
        },
    }
    on = s.summary.online
    assert on is not None
    out["online_synthetic_archive"] = {
        "records": on.population_total + sum(on.excluded_counts.values()),
        "excluded": on.excluded_counts,
        "sampled": on.sampled_total,
        "evaluated": on.evaluated_total,
        "status": on.status,
        "limited_dimensions": on.limited_dimensions,
        "results": len(on.results),
    }

    commercial = await sp.run_slice(cloud="commercial", with_online=False, drift=False)
    reg = commercial.registry
    cfg = sp.judge_config(reg, sp.COMM_LLM)
    out["commercial_pilot"] = {
        "skip_counts": commercial.summary.offline.skip_counts,
        "judge_calls": commercial.fixture.call_count,
        "availability": judge_availability(cfg, commercial.matrix),
    }

    tight = await sp.run_slice(
        budget=BudgetLimits(tokens=6_000, cost=Decimal("1")), with_online=False, drift=False
    )
    t = tight.summary.offline
    out["budget_run_6000_tokens"] = {
        "status": t.status,
        "reason": t.budget_exhausted_reason,
        "evaluated": t.evaluated_total,
        "unevaluated": t.unevaluated_total,
        "skip_counts": t.skip_counts,
        "tokens_used": sum(u.input_tokens + u.output_tokens for u in t.usage),
        "results_emitted": len(t.results),
        "uncalibrated_judges": list(t.uncalibrated_judges),
        "calibrations_stored": tight.summary.calibrations_stored,
    }

    with tempfile.TemporaryDirectory(prefix="ns-eval-measure-") as tmp:
        path = sp.generate_government_telemetry(Path(tmp))
        lines = [ln for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]
        registry = sp.build_registry()
        registry.datasets.register(sp.frame_dataset())
        double = sp.CountingLlm()
        service = EvaluationService(
            judge=double,
            matrix=s.matrix,
            registry=registry,
            ledger=sp.ledger(),
            clock=sp.clock,
        )
        report = await service.run_online(
            NdjsonRecordSource(path), sp.online_config(registry, run_id="online-sandbox", llm=True)
        )
        out["online_sandbox_telemetry"] = {
            "records": len(lines),
            "with_classification_field": sum('"classification"' in ln for ln in lines),
            "excluded": report.excluded_counts,
            "sampled": report.sampled_total,
            "skip_counts": report.skip_counts,
            "judge_calls": len(double.calls),
            "evaluated": report.evaluated_total,
        }

    print(json.dumps(out, indent=2, default=str))


if __name__ == "__main__":
    asyncio.run(main())
