"""The CI python test shards must cover exactly the pytest `testpaths`.

The python suite is split across matrix jobs by top-level test root. A root that
is in `testpaths` but in no shard would silently stop running in CI, so this
test pins the two lists together and checks the gate job that keeps the
required check name.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
GATE_NAME = "python (ruff, pyright, pytest, pip-audit)"


def _jobs() -> dict:
    workflow = yaml.safe_load(
        (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    )
    return workflow["jobs"]


def test_shards_cover_testpaths_exactly_once() -> None:
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    testpaths = pyproject["tool"]["pytest"]["ini_options"]["testpaths"]
    shards = _jobs()["python-tests"]["strategy"]["matrix"]["shard"]
    covered = [path for shard in shards for path in shard["paths"].split()]
    assert sorted(covered) == sorted(testpaths)
    assert len(covered) == len(set(covered))


def test_shards_run_the_default_marker_selection() -> None:
    steps = _jobs()["python-tests"]["steps"]
    commands = [step["run"] for step in steps if step.get("name") == "Pytest"]
    assert commands == ["uv run pytest -q ${{ matrix.shard.paths }}"]


def test_gate_keeps_the_required_name_and_needs_every_python_job() -> None:
    jobs = _jobs()
    gate = jobs["python"]
    assert gate["name"] == GATE_NAME
    assert sorted(gate["needs"]) == ["python-static", "python-tests"]
    assert gate["if"] == "always()"
    script = gate["steps"][0]["run"]
    assert 'test "$STATIC" = "success"' in script
    assert 'test "$TESTS" = "success"' in script
    assert jobs["python-tests"]["strategy"]["fail-fast"] is False
