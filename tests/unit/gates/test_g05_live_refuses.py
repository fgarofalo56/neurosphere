"""G05 live swap script refuses without NS_LIVE_APPROVED=1, before any SDK import or network."""

from __future__ import annotations

import ast
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from neurosphere_core.errors import CapabilityUnavailableError, DependencyTransientError

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


# -- orchestration: rollback always runs once apply was attempted (no network; fake connector) --


class _Reader:
    async def get_deployment(self, name: str) -> dict[str, Any]:
        return {
            "etag": "etag-1",
            "properties": {
                "model": {"format": "OpenAI", "name": "gpt-4o", "version": "2024-08-06"}
            },
        }


class _FakeConnector:
    def __init__(self, *, apply_exc: Exception | None = None, verify_exc: Exception | None = None):
        self.apply_exc = apply_exc
        self.verify_exc = verify_exc
        self.rolled: list[Any] = []

    async def dry_run(self, request: Any) -> Any:
        return SimpleNamespace(would_change=True)

    async def check_compatibility(self, request: Any) -> list[Any]:
        return []

    async def apply(self, request: Any) -> Any:
        if self.apply_exc:
            raise self.apply_exc
        return SimpleNamespace(version_before="etag-1", version_after="etag-2")

    async def verify(self, request: Any) -> Any:
        if self.verify_exc and request.target_version == "etag-2":
            raise self.verify_exc
        return SimpleNamespace(matched=True, mismatched_paths=())

    async def rollback(self, applied: Any) -> Any:
        self.rolled.append(applied)
        return SimpleNamespace(status="rolled_back", version_after=None)


def _load_script() -> Any:
    spec = importlib.util.spec_from_file_location("g05_script", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


async def _drive(connector: _FakeConnector) -> tuple[bool, list[dict[str, Any]]]:
    steps: list[dict[str, Any]] = []

    def record(step: str, **fields: Any) -> None:
        steps.append({"step": step, **fields})

    ok = await _load_script()._exercise(
        connector,
        _Reader(),
        name="dep1",
        customer="cust1",
        target_model="gpt-4.1",
        target_version="2025-04-14",
        record=record,
    )
    return ok, steps


async def test_rollback_runs_from_pre_read_model_when_apply_raises_after_put() -> None:
    err = CapabilityUnavailableError("apply_failed_restore_failed", "x")
    connector = _FakeConnector(apply_exc=err)
    ok, steps = await _drive(connector)
    assert ok is False
    assert len(connector.rolled) == 1
    applied = connector.rolled[0]
    assert applied.version_after is None
    assert json.loads(applied.rollback_token) == {
        "format": "OpenAI",
        "name": "gpt-4o",
        "version": "2024-08-06",
    }
    assert [s["step"] for s in steps][-2:] == ["rollback", "verify_after_rollback"]


async def test_rollback_skipped_when_connector_already_restored() -> None:
    connector = _FakeConnector(apply_exc=CapabilityUnavailableError("apply_failed_restored", "x"))
    ok, steps = await _drive(connector)
    assert ok is False
    assert connector.rolled == []
    skipped = [s for s in steps if s["step"] == "rollback"]
    assert skipped and skipped[0]["status"] == "skipped_connector_restored"


async def test_rollback_runs_when_verify_raises() -> None:
    connector = _FakeConnector(verify_exc=DependencyTransientError(reason="transient"))
    ok, steps = await _drive(connector)
    assert ok is False
    assert len(connector.rolled) == 1
    assert connector.rolled[0].version_after == "etag-2"
    assert steps[-1]["step"] == "verify_after_rollback"


async def test_happy_path_passes_and_rolls_back_with_current_etag() -> None:
    connector = _FakeConnector()
    ok, steps = await _drive(connector)
    assert ok is True
    assert len(connector.rolled) == 1
    assert steps[-1]["matched"] is True
