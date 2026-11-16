"""``scripts/gates/deploy_apply_live.py`` refuses without ``NS_LIVE_APPROVED=1`` (PRP-55 item 6,
criterion 9): non-zero exit, no Azure or project import, nothing written."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

SCRIPT = Path(__file__).resolve().parents[4] / "scripts" / "gates" / "deploy_apply_live.py"
SUB = "aaaaaaaa-0000-4000-8000-000000000001"
ARGS = [
    "--subscription",
    SUB,
    "--resource-group",
    "rg-throwaway",
    "--region",
    "eastus2",
    "--deployment-id",
    "ns-live-20261116",
]


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("ns_deploy_apply_live_for_tests", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("value", [None, "", "0", "true", "yes"])
def test_refuses_without_approval(
    value: str | None, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    if value is None:
        monkeypatch.delenv("NS_LIVE_APPROVED", raising=False)
    else:
        monkeypatch.setenv("NS_LIVE_APPROVED", value)
    module = _load()
    evidence = module.EVIDENCE_DIR
    before = sorted(evidence.glob("*")) if evidence.exists() else []
    assert module.main(ARGS) == 2
    assert "REFUSED" in capsys.readouterr().err
    after = sorted(evidence.glob("*")) if evidence.exists() else []
    assert after == before


def test_refusal_imports_no_azure_or_project_code() -> None:
    code = (
        "import runpy, sys\n"
        f"sys.argv = ['deploy_apply_live.py', *{ARGS!r}]\n"
        "try:\n"
        f"    runpy.run_path({str(SCRIPT)!r}, run_name='__main__')\n"
        "except SystemExit as exc:\n"
        "    loaded = [m for m in sys.modules if m.split('.')[0] in "
        "('azure', 'httpx', 'neurosphere_core', 'neurosphere_workers', 'neurosphere_api')]\n"
        "    print(exc.code, len(loaded))\n"
    )
    env = {k: v for k, v in __import__("os").environ.items() if k != "NS_LIVE_APPROVED"}
    result = subprocess.run(  # noqa: S603 - fixed interpreter and fixed probe text
        [sys.executable, "-c", code], capture_output=True, text=True, timeout=120, env=env
    )
    assert result.stdout.split() == ["2", "0"], result.stderr


def test_approved_but_invalid_arguments_are_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NS_LIVE_APPROVED", "1")
    module = _load()
    assert module.main([*ARGS[:1], "not-a-guid", *ARGS[2:]]) == 2
    assert module.main(["--subscription", SUB]) == 2  # missing required arguments


def test_subscription_ids_are_tokenised() -> None:
    module = _load()
    token = module.tokenise(SUB)
    assert token.startswith("sub-") and SUB not in token
    assert module._scrub(f"/subscriptions/{SUB.upper()}/x", SUB) == f"/subscriptions/{token}/x"
