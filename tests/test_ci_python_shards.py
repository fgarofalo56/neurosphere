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


def _invocations() -> list[tuple[list[str], list[str]]]:
    """One (paths, ignored paths) pair per pytest invocation across all shards."""
    shards = _jobs()["python-tests"]["strategy"]["matrix"]["shard"]
    result: list[tuple[list[str], list[str]]] = []
    for shard in shards:
        for line in shard["invocations"].splitlines():
            tokens = line.split()
            if not tokens:
                continue
            ignores = [t.removeprefix("--ignore=") for t in tokens if t.startswith("--ignore=")]
            paths = [t for t in tokens if not t.startswith("-")]
            assert len(paths) + len(ignores) == len(tokens), f"unexpected flag in {line!r}"
            result.append((paths, ignores))
    return result


def test_shards_cover_testpaths_exactly_once() -> None:
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    testpaths = pyproject["tool"]["pytest"]["ini_options"]["testpaths"]
    # `services` is run per member (api, workers, docs-assistant); services/api is split further.
    expected: list[str] = []
    for root in testpaths:
        if root == "services":
            expected += sorted(
                f"services/{p.name}" for p in (ROOT / "services").iterdir() if p.is_dir()
            )
        else:
            expected.append(root)

    # Every path a shard names, and the directories its --ignore flags carve out of it.
    named = [path for paths, _ in _invocations() for path in paths]
    ignored = [path for _, ignores in _invocations() for path in ignores]
    sub_paths = [p for p in named if p.startswith("services/api/tests/")]
    whole = [p for p in named if p not in sub_paths]

    # The explicitly named api sub-directories must equal what the other api shard ignores,
    # so each api test runs in exactly one shard.
    assert sorted(sub_paths) == sorted(ignored)
    assert len(sub_paths) == len(set(sub_paths))
    for path in sub_paths:
        assert (ROOT / path).is_dir(), path
    assert sorted(whole) == sorted(expected)
    assert len(whole) == len(set(whole))


def test_shards_run_the_default_marker_selection() -> None:
    steps = _jobs()["python-tests"]["steps"]
    pytest_steps = [step for step in steps if step.get("name") == "Pytest"]
    assert len(pytest_steps) == 1
    script = pytest_steps[0]["run"]
    assert "uv run pytest -q $args || rc=1" in script
    assert script.rstrip().endswith("exit $rc")
    assert "-m " not in script


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
