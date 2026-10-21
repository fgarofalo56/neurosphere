"""G05 live swap script refuses without NS_LIVE_APPROVED=1, before any SDK import or network."""

from __future__ import annotations

import ast
import os
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "gates" / "g05_foundry_swap_live.py"
ARGS = [
    "--subscription",
    "00000000-1111-2222-3333-444444444444",
    "--resource-group",
    "rg",
    "--account",
    "acct1",
    "--location",
    "eastus2",
    "--deployment",
    "dep1",
    "--target-model",
    "gpt-4.1",
    "--target-version",
    "2025-04-14",
]


def _run(env_extra: dict[str, str], *args: str) -> subprocess.CompletedProcess[str]:
    env = {k: v for k, v in os.environ.items() if k != "NS_LIVE_APPROVED"}
    env.update(env_extra)
    return subprocess.run(
        [sys.executable, "-I", str(SCRIPT), *args],
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
        check=False,
    )


def test_refuses_without_approval_with_and_without_args() -> None:
    for args in ((), tuple(ARGS)):
        proc = _run({}, *args)
        assert proc.returncode == 2
        assert "REFUSED" in proc.stderr
        assert "NS_LIVE_APPROVED=1" in proc.stderr
        assert proc.stdout == ""


def test_refuses_for_any_value_other_than_one() -> None:
    for value in ("0", "true", ""):
        assert _run({"NS_LIVE_APPROVED": value}, *ARGS).returncode == 2


def test_top_level_imports_are_stdlib_only() -> None:
    """The refusal path can never touch Azure SDKs or the network: no non-stdlib top imports."""
    tree = ast.parse(SCRIPT.read_text(encoding="utf-8"))
    top: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.Import):
            top.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            top.add((node.module or "").split(".")[0])
    assert top <= set(sys.stdlib_module_names) | {"__future__"}


def test_refusal_check_precedes_argument_parsing_and_imports() -> None:
    tree = ast.parse(SCRIPT.read_text(encoding="utf-8"))
    main = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "main")
    first = ast.unparse(main.body[0])
    assert first.startswith("if os.environ.get('NS_LIVE_APPROVED') != '1'")
