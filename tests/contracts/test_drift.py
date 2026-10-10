"""Drift check: committed bindings equal a fresh regeneration (PRP-01 item 6 / 7, ADR-0004).

``generate.py --check`` regenerates both trees into a temporary directory and exits 1 on
any difference. The second test proves the check bites: a copy of the schema tree with one
added property regenerates to different bindings, so "adding a property to a schema
without regenerating fails the suite".

The generators (datamodel-code-generator via uv, json-schema-to-typescript via node) are
local tools; without them these tests skip, unless ``NS_CODEGEN_REQUIRED=1`` (the same
switch packages/contracts/scripts/test_generate.py uses), which turns a missing toolchain
into a failure.
"""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest
from contract_support import CONTRACTS_DIR, REPO_ROOT, SCHEMA_ROOT

GENERATE = CONTRACTS_DIR / "scripts" / "generate.py"
MUTATED_SCHEMA = "query/v1/page.schema.json"


def _load_generate() -> ModuleType:
    spec = importlib.util.spec_from_file_location("ns_contracts_generate", GENERATE)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _toolchain_or_skip(gen: ModuleType) -> None:
    try:
        gen.check_toolchain()
    except gen.ToolchainError as exc:
        if os.environ.get("NS_CODEGEN_REQUIRED") == "1":
            pytest.fail(f"NS_CODEGEN_REQUIRED=1 but the generator toolchain is missing: {exc}")
        pytest.skip(f"generator toolchain not installed: {exc}")


@pytest.fixture
def offline_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """uv must resolve from the local environment only."""
    monkeypatch.setenv("UV_OFFLINE", "1")


@pytest.mark.usefixtures("offline_env")
def test_committed_bindings_match_regeneration() -> None:
    gen = _load_generate()
    _toolchain_or_skip(gen)
    proc = subprocess.run(
        [sys.executable, str(GENERATE), "--check"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=600,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert proc.stdout.startswith("OK:"), proc.stdout


def test_diff_trees_reports_every_kind_of_drift() -> None:
    gen = _load_generate()
    committed = gen.read_tree(gen.PY_OUT, ".py")
    assert committed, "no committed Python bindings found"
    first = sorted(committed)[0]
    assert gen.diff_trees("py", committed, dict(committed)) == []
    mutated = {**committed, first: committed[first] + "# drift\n"}
    assert any(line.startswith("differs:") for line in gen.diff_trees("py", committed, mutated))
    missing = {k: c for k, c in committed.items() if k != first}
    assert any(line.startswith("stale") for line in gen.diff_trees("py", committed, missing))
    extra = {**committed, "zz_new.py": "x = 1\n"}
    assert any(line.startswith("missing") for line in gen.diff_trees("py", committed, extra))


@pytest.mark.usefixtures("offline_env")
def test_schema_change_without_regeneration_is_detected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    gen = _load_generate()
    _toolchain_or_skip(gen)
    schemas = tmp_path / "schemas"
    shutil.copytree(SCHEMA_ROOT, schemas)
    target = schemas / MUTATED_SCHEMA
    document = json.loads(target.read_text(encoding="utf-8"))
    document["properties"]["drift_probe"] = {"type": ["string", "null"]}
    target.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    monkeypatch.setattr(gen, "SCHEMA_ROOT", schemas)

    python_tree, ts_tree = gen.generate_all()
    problems = gen.diff_trees("py", gen.read_tree(gen.PY_OUT, ".py"), python_tree)
    problems += gen.diff_trees("ts", gen.read_tree(gen.TS_OUT, ".ts"), ts_tree)
    assert any("query/v1/page.py" in p for p in problems), problems[:10]
    assert any("query/v1/page.ts" in p for p in problems), problems[:10]
    assert any("drift_probe" in p for p in problems)
