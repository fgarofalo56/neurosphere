from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path

from neurosphere_contracts.query.v1.budget import Budget
from neurosphere_core.search import AuthorizedSearch, SearchRequest
from neurosphere_core.search.fixture import FixtureSearchIndex, documents_from_catalog

from .search_helpers import cid, corpus, make_scope

BUDGET = Budget(timeout_ms=5000, limit=50, max_depth=0)
HERE = Path(__file__).resolve().parent


def run_once() -> list[tuple[str, float]]:
    index = FixtureSearchIndex(documents_from_catalog(corpus()))
    scope = make_scope([cid("domain", "alpha"), cid("domain", "beta")])
    res = asyncio.run(index.search(scope, SearchRequest(term="triage tickets", budget=BUDGET)))
    return [(h.id, h.score) for h in res.hits]


def test_protocol_conformance() -> None:
    assert isinstance(FixtureSearchIndex([]), AuthorizedSearch)


def test_repeated_runs_identical() -> None:
    first = run_once()
    assert first
    for _ in range(5):
        assert run_once() == first


def test_ties_break_by_canonical_id_ascending() -> None:
    docs = documents_from_catalog(corpus())
    index = FixtureSearchIndex(list(reversed(docs)))  # insertion order must not matter
    scope = make_scope([cid("domain", "alpha")])
    res = asyncio.run(index.search(scope, SearchRequest(term="triage", budget=BUDGET)))
    assert len(res.hits) > 1
    for a, b in zip(res.hits, res.hits[1:], strict=False):
        assert (-a.score, a.id) < (-b.score, b.id)


def test_identical_across_processes() -> None:
    code = (
        "import json; from search.test_fixture_determinism import run_once; "
        "print(json.dumps(run_once()))"
    )
    outs = []
    for seed in ("0", "12345"):  # different hash seeds must not change results
        proc = subprocess.run(  # noqa: S603
            [sys.executable, "-c", code],
            cwd=HERE,
            env={**os.environ, "PYTHONHASHSEED": seed, "PYTHONPATH": str(HERE.parent)},
            capture_output=True,
            text=True,
            check=True,
            timeout=120,
        )
        outs.append(json.loads(proc.stdout.strip().splitlines()[-1]))
    assert outs[0] == outs[1] == [list(p) for p in run_once()]
