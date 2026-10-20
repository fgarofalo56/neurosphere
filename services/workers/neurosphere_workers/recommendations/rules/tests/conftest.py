"""Session fixtures: sandbox data is generated once per seed into a temp dir (tests may import
``sandbox``; production code only reads its output files)."""

from __future__ import annotations

import json
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from neurosphere_workers.recommendations.rules import (
    RuleResult,
    SandboxSeriesSource,
    evaluate_rules,
)
from neurosphere_workers.recommendations.rules.tests.support import (
    CREATED_AT,
    END,
    REPO_ROOT,
    START,
    ListSource,
    make_scope,
)

SEEDS = (3, 11)


def _generate(seed: int, out: Path) -> None:
    """Generate sandbox data. Small but dense: 7 days (baseline 3 + recent 4), about 20 traces per
    agent per day so daily statistics are meaningful, bad events at the default sandbox rates."""
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))
    from sandbox.config import BadEventRates, GenerateConfig, Profile
    from sandbox.generate import generate

    profile = Profile(
        "custom",
        domains=4,
        agents=40,
        days=7,
        traces_per_agent_day=20.0,
        cost_spikes=3,
        latency_regressions=3,
        unused_agents=3,
        duplicate_pairs=1,
    )
    generate(
        GenerateConfig(seed=seed, profile=profile, cloud="commercial", rates=BadEventRates()), out
    )


@dataclass(frozen=True)
class SandboxRun:
    directory: Path
    source: SandboxSeriesSource
    results: list[RuleResult]
    domains: list[str]
    manifest: dict[str, Any]

    def anomalies(self, kind: str) -> set[str]:
        return {
            agent
            for a in self.manifest["anomalies"]
            if a["type"] == kind
            for agent in a["affected_ids"]
        }

    def detected(self, rule_id: str) -> set[str]:
        return {
            r.agent_id for r in self.results if r.rule_id == rule_id and r.outcome == "detected"
        }


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture(scope="session", params=SEEDS, ids=lambda s: f"seed{s}")
def sandbox_run(
    request: pytest.FixtureRequest, tmp_path_factory: pytest.TempPathFactory
) -> SandboxRun:
    out = tmp_path_factory.mktemp(f"rules-sandbox-{request.param}")
    _generate(request.param, out)
    source = SandboxSeriesSource(out)
    window = source.observed_window()
    assert window is not None
    domains = [
        json.loads(line)["id"]
        for line in (out / "domains.ndjson").read_text(encoding="utf-8").splitlines()
    ]
    results = evaluate_rules(
        source,
        scope=make_scope(tuple(domains)),
        window_start=window[0],
        window_end=window[1],
        created_at=CREATED_AT,
    )
    return SandboxRun(out, source, results, domains, _read_json(out / "anomaly-manifest.json"))


@pytest.fixture
def evaluate() -> Callable[..., list[RuleResult]]:
    """Evaluate constructed series over the support window with the default scope."""

    def run(*series: Any, **kw: Any) -> list[RuleResult]:
        scope = kw.pop("scope", None) or make_scope()
        return evaluate_rules(
            ListSource(*series),
            scope=scope,
            window_start=kw.pop("start", START),
            window_end=kw.pop("end", END),
            created_at=CREATED_AT,
            **kw,
        )

    return run
