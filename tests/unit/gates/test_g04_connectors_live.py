"""G04 live gate: refuses first, validates arguments, scrubs evidence. No live call happens here."""

from __future__ import annotations

import ast
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "gates" / "g04_connectors_live.py"
WORKSPACE = "11111111-2222-3333-4444-555555555555"
ENDPOINT = "https://acct-secretname.services.ai.azure.com/api/projects/proj-secretname"
BLOB_URL = "https://exportacct1.blob.core.windows.net"
BASE = [
    "--budget-cap-usd",
    "5",
    "--operator",
    "tester",
    "--monitor-workspace-id",
    WORKSPACE,
    "--foundry-project-endpoint",
    ENDPOINT,
    "--billing-account-url",
    BLOB_URL,
    "--billing-container",
    "exports-secretname",
    "--billing-manifest-blob",
    "run/manifest.json",
]
ALL_STEPS = [
    "--approve-step",
    "azure-monitor",
    "--approve-step",
    "foundry-discovery",
    "--approve-step",
    "billing-export",
]


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("g04_under_test", SCRIPT)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def _subprocess(env_extra: dict[str, str], *args: str) -> subprocess.CompletedProcess[str]:
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


def test_refuses_without_approval_before_anything_else() -> None:
    for args in ((), (*BASE, *ALL_STEPS)):
        proc = _subprocess({}, *args)
        assert proc.returncode == 2
        assert "REFUSED" in proc.stderr and "NS_LIVE_APPROVED=1" in proc.stderr
        assert proc.stdout == ""


@pytest.mark.parametrize("value", ["0", "true", "", "yes"])
def test_any_value_other_than_one_refuses(value: str) -> None:
    assert _subprocess({"NS_LIVE_APPROVED": value}, *BASE, *ALL_STEPS).returncode == 2


def test_top_level_imports_are_os_and_sys_only_and_refusal_is_first() -> None:
    tree = ast.parse(SCRIPT.read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.Import):
            imported.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module != "__future__":
            imported.add(node.module or "")
    assert imported == {"os", "sys"}
    main = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "main")
    first = main.body[0]
    assert isinstance(first, ast.If)
    assert "NS_LIVE_APPROVED" in ast.unparse(first.test)


def _run(
    monkeypatch: pytest.MonkeyPatch,
    argv: list[str],
    runners: dict[str, Any] | None = None,
) -> tuple[ModuleType, int]:
    monkeypatch.setenv("NS_LIVE_APPROVED", "1")
    mod = _load()
    return mod, mod.main(argv, runners)


def test_government_is_refused(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _, rc = _run(monkeypatch, ["--cloud", "government", *BASE, *ALL_STEPS])
    assert rc == 2
    assert "Commercial only" in capsys.readouterr().err


@pytest.mark.parametrize(
    "args",
    [
        ["--operator", "tester", *ALL_STEPS],  # no budget cap
        ["--budget-cap-usd", "0", "--operator", "tester", *ALL_STEPS],
        ["--budget-cap-usd", "9999", "--operator", "tester", *ALL_STEPS],
        [*BASE],  # no approved step
        ["--budget-cap-usd", "5", *ALL_STEPS],  # no operator
        ["--budget-cap-usd", "5", "--operator", "tester", "--approve-step", "azure-monitor"],
        [*BASE, "--foundry-project-endpoint", "http://insecure.example.invalid", *ALL_STEPS],
    ],
)
def test_argument_preconditions_refuse(monkeypatch: pytest.MonkeyPatch, args: list[str]) -> None:
    ran: list[str] = []

    async def runner(_: Any) -> dict[str, Any]:
        ran.append("x")
        return {"connector": "x", "ok": True}

    runners = {k: runner for k in ("azure-monitor", "foundry-discovery", "billing-export")}
    _, rc = _run(monkeypatch, args, runners)
    assert rc == 2
    assert ran == []


def test_unapproved_connectors_do_not_run(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    ran: list[str] = []

    def make(name: str) -> Any:
        async def runner(_: Any) -> dict[str, Any]:
            ran.append(name)
            return {"connector": name, "ok": True, "contract_violations": [], "read": {}}

        return runner

    runners = {k: make(k) for k in ("azure-monitor", "foundry-discovery", "billing-export")}
    _, rc = _run(
        monkeypatch,
        [*BASE, "--approve-step", "azure-monitor", "--evidence-dir", str(tmp_path)],
        runners,
    )
    assert rc == 0
    assert ran == ["azure-monitor"]


def test_exit_zero_only_after_run_and_evidence_is_scrubbed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    async def leaky(_: Any) -> dict[str, Any]:
        return {
            "connector": "azure-monitor",
            "ok": True,
            "contract_violations": [],
            "read": {
                "note": f"queried {WORKSPACE} at {ENDPOINT} in exports-secretname",
                "arm": "/subscriptions/abc/resourceGroups/rg-1/providers/x/y/z",
            },
        }

    runners = {
        "azure-monitor": leaky,
        "foundry-discovery": leaky,
        "billing-export": leaky,
    }
    _, rc = _run(monkeypatch, [*BASE, *ALL_STEPS, "--evidence-dir", str(tmp_path)], runners)
    assert rc == 0
    (evidence,) = tmp_path.glob("connectors-*.json")
    text = evidence.read_text(encoding="utf-8")
    for leaked in (WORKSPACE, "secretname", "acct-", "exportacct1", "rg-1", "/subscriptions/"):
        assert leaked not in text
    document = json.loads(text)
    assert document["result"] == "PASS" and document["budget_cap_usd"] == 5.0
    assert document["approved_steps"] == ["azure-monitor", "foundry-discovery", "billing-export"]


def test_contract_failure_exits_one(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    async def bad(_: Any) -> dict[str, Any]:
        return {
            "connector": "azure-monitor",
            "ok": False,
            "contract_violations": ["health_type"],
            "read": {},
        }

    _, rc = _run(
        monkeypatch,
        [*BASE, "--approve-step", "azure-monitor", "--evidence-dir", str(tmp_path)],
        {"azure-monitor": bad},
    )
    assert rc == 1
    assert json.loads(next(tmp_path.glob("*.json")).read_text(encoding="utf-8"))["result"] == "FAIL"


def test_missing_prerequisite_is_open_not_pass(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    async def boom(_: Any) -> dict[str, Any]:
        raise RuntimeError(f"cannot reach {ENDPOINT}")

    _, rc = _run(
        monkeypatch,
        [*BASE, "--approve-step", "foundry-discovery", "--evidence-dir", str(tmp_path)],
        {"foundry-discovery": boom},
    )
    out = capsys.readouterr().out
    assert rc == 3
    assert "OPEN" in out and "RuntimeError" in out
    assert ENDPOINT not in out  # the exception message may name a resource and is never echoed
    assert list(tmp_path.glob("*.json")) == []
