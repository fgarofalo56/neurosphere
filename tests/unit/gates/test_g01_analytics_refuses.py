"""G01 analytics live gate: approval, cloud refusal, adapter selection, OPEN and exit rule.

No network, no Azure and no subprocess to Azure: runners are injected fakes. The one subprocess
runs the script itself with a clean environment to prove the refusal path imports nothing.
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "gates" / "g01_analytics_live.py"
DBX_HOST = "adb-1234567890123456.7.azuredatabricks.net"
DBX_GOV_HOST = "adb-1234567890123456.7.databricks.azure.us"
FABRIC_HOST = "abc123.datawarehouse.fabric.microsoft.com"
FABRIC_GOV_HOST = "abc123.fabric.microsoft.us"


def load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("g01_analytics_under_test", SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["g01_analytics_under_test"] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in list(os.environ):
        if key.startswith("NS_G01A_") or key == "NS_LIVE_APPROVED":
            monkeypatch.delenv(key, raising=False)


def approve(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NS_LIVE_APPROVED", "1")


def databricks_env(monkeypatch: pytest.MonkeyPatch, host: str = DBX_HOST) -> None:
    monkeypatch.setenv("NS_G01A_DATABRICKS_HOST", host)
    monkeypatch.setenv("NS_G01A_DATABRICKS_WAREHOUSE_ID", "0123456789abcdef")
    monkeypatch.setenv("NS_G01A_DATABRICKS_CATALOG", "main")
    monkeypatch.setenv("NS_G01A_DATABRICKS_REGION", "eastus2")


# ----------------------------------------------------------------------------- approval


def test_refuses_without_approval_and_writes_nothing(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    code = load().main(["--adapter", "fabric", "--evidence-dir", str(tmp_path / "ev")])
    assert code == 2
    err = capsys.readouterr().err
    assert "REFUSED" in err
    assert "NS_LIVE_APPROVED=1" in err
    assert not (tmp_path / "ev").exists()


def test_approval_must_be_exactly_one(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("NS_LIVE_APPROVED", "true")
    assert load().main(["--adapter", "fabric"]) == 2
    assert "REFUSED" in capsys.readouterr().err


def test_refusal_runs_before_argument_parsing(capsys: pytest.CaptureFixture[str]) -> None:
    # No --adapter at all: argparse would exit 2 with its own usage text; ours comes first.
    assert load().main([]) == 2
    err = capsys.readouterr().err
    assert "NS_LIVE_APPROVED=1" in err
    assert "usage:" not in err


def test_refusal_path_imports_no_project_azure_or_httpx() -> None:
    env = {k: v for k, v in os.environ.items() if k != "NS_LIVE_APPROVED"}
    probe = (
        "import importlib.util, sys\n"
        f"spec = importlib.util.spec_from_file_location('g', {str(SCRIPT)!r})\n"
        "mod = importlib.util.module_from_spec(spec)\n"
        "sys.modules['g'] = mod\n"
        "spec.loader.exec_module(mod)\n"
        "code = mod.main(['--adapter', 'fabric'])\n"
        "bad = sorted(m for m in sys.modules if m.split('.')[0] in "
        "{'neurosphere_core', 'neurosphere_contracts', 'httpx', 'azure'})\n"
        "print('code=%d bad=%s' % (code, bad))\n"
    )
    proc = subprocess.run(
        [sys.executable, "-c", probe],
        capture_output=True,
        text=True,
        env=env,
        check=False,
        timeout=60,
    )
    assert "code=2 bad=[]" in proc.stdout, proc.stdout + proc.stderr
    assert "REFUSED" in proc.stderr


# ----------------------------------------------------------------------------- arguments


def test_unknown_adapter_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    approve(monkeypatch)
    assert load().main(["--adapter", "clickhouse"]) == 2


def test_adapter_is_required(monkeypatch: pytest.MonkeyPatch) -> None:
    approve(monkeypatch)
    assert load().main([]) == 2


def test_no_credential_arguments_exist() -> None:
    parser = load().build_parser()
    flags = {opt for action in parser._actions for opt in action.option_strings}  # pyright: ignore[reportPrivateUsage]
    assert not any(w in f for f in flags for w in ("token", "key", "pat", "password", "secret"))


# ----------------------------------------------------------------------------- Government


@pytest.mark.parametrize(
    ("adapter", "env"),
    [
        ("databricks", {"NS_G01A_DATABRICKS_REGION": "usgovvirginia"}),
        ("databricks", {"NS_G01A_DATABRICKS_HOST": DBX_GOV_HOST}),
        ("fabric", {"NS_G01A_FABRIC_REGION": "usgovtexas"}),
        ("fabric", {"NS_G01A_FABRIC_HOST": FABRIC_GOV_HOST}),
        ("synapse", {"NS_G01A_SYNAPSE_HOST": "ws.sql.azuresynapse.usgovcloudapi.net"}),
        ("synapse", {"NS_G01A_SYNAPSE_REGION": "usdodeast"}),
    ],
)
def test_government_cloud_region_or_host_is_refused(
    adapter: str,
    env: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    approve(monkeypatch)
    if adapter == "databricks":
        databricks_env(monkeypatch)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    called: list[str] = []

    async def runner(settings: object, options: object):
        called.append("ran")
        raise AssertionError("must not run")

    code = load().main(
        ["--adapter", adapter, "--evidence-dir", str(tmp_path)], runners={adapter: runner}
    )
    assert code == 2
    assert "REFUSED" in capsys.readouterr().err
    assert called == []
    assert list(tmp_path.iterdir()) == []


def test_cross_cloud_host_refused_by_the_adapter_config_model(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A Commercial region with a host of the wrong shape fails at config construction."""
    approve(monkeypatch)
    databricks_env(monkeypatch, host="adb-1.7.example.com")
    assert load().main(["--adapter", "databricks"]) == 2
    assert "configuration refused" in capsys.readouterr().err


def test_databricks_needs_its_config(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    approve(monkeypatch)
    assert load().main(["--adapter", "databricks"]) == 2
    assert "NS_G01A_DATABRICKS_HOST" in capsys.readouterr().err


def test_all_adapters_validated_before_any_runs(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    approve(monkeypatch)  # databricks config missing -> nothing at all runs, not even fabric
    ran: list[str] = []

    async def runner(settings: object, options: object):
        ran.append("x")
        raise AssertionError

    code = load().main(
        ["--adapter", "fabric", "--adapter", "databricks", "--evidence-dir", str(tmp_path)],
        runners={"fabric": runner, "databricks": runner},
    )
    assert code == 2
    assert ran == []


# ----------------------------------------------------------------------------- selection


def make_runner(mod: ModuleType, status: str, log: list[str], name: str):
    async def runner(settings: object, options: object):
        log.append(name)
        return mod.AdapterResult(status=status, reason=f"{name} {status}")

    return runner


def test_only_named_adapters_run(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    approve(monkeypatch)
    mod = load()
    log: list[str] = []
    runners = {n: make_runner(mod, "PASS", log, n) for n in mod.ADAPTERS}
    code = mod.main(
        ["--adapter", "synapse", "--adapter", "synapse", "--evidence-dir", str(tmp_path)],
        runners=runners,
    )
    assert code == 0
    assert log == ["synapse"]  # named once, others untouched
    assert [p.name.endswith("-synapse-commercial.json") for p in tmp_path.glob("*.json")] == [True]


def test_adapters_are_independent(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    approve(monkeypatch)
    mod = load()
    log: list[str] = []

    async def crash(settings: object, options: object):
        log.append("fabric")
        raise RuntimeError("boom")

    runners = {
        "fabric": crash,
        "synapse": make_runner(mod, "OPEN", log, "synapse"),
        "databricks": make_runner(mod, "PASS", log, "databricks"),
    }
    databricks_env(monkeypatch)
    code = mod.main(
        [
            "--adapter",
            "fabric",
            "--adapter",
            "synapse",
            "--adapter",
            "databricks",
            "--evidence-dir",
            str(tmp_path),
        ],
        runners=runners,
    )
    assert log == ["fabric", "synapse", "databricks"]  # the crash did not stop the others
    by_adapter = {
        json.loads(p.read_text(encoding="utf-8"))["adapter"]: json.loads(
            p.read_text(encoding="utf-8")
        )["status"]
        for p in tmp_path.glob("*.json")
    }
    assert by_adapter == {"fabric": "FAIL", "synapse": "OPEN", "databricks": "PASS"}
    assert code == 1


@pytest.mark.parametrize(
    ("statuses", "expected"),
    [
        (["PASS"], 0),
        (["PASS", "PASS"], 0),
        (["OPEN"], 3),
        (["PASS", "OPEN"], 3),
        (["FAIL"], 1),
        (["PASS", "OPEN", "FAIL"], 1),  # FAIL wins over OPEN
        (["OPEN", "FAIL"], 1),
    ],
)
def test_exit_code_rule(statuses: list[str], expected: int) -> None:
    assert load().exit_code(statuses) == expected


# ----------------------------------------------------------------------------- OPEN adapters


@pytest.mark.parametrize("adapter", ["fabric", "synapse"])
def test_fabric_and_synapse_are_open_with_the_driver_reason(
    adapter: str, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    approve(monkeypatch)
    monkeypatch.setenv("NS_G01A_OPERATOR", "test-operator")
    code = load().main(["--adapter", adapter, "--evidence-dir", str(tmp_path)])
    assert code == 3
    evidence = json.loads(next(tmp_path.glob(f"*-{adapter}-commercial.json")).read_text("utf-8"))
    assert evidence["status"] == "OPEN"
    assert "no approved TDS driver" in evidence["reason"]
    assert "mssql-python or ODBC Driver 18" in evidence["reason"]
    assert "ADR-0002" in evidence["reason"]
    assert "No connection was attempted" in evidence["reason"]
    assert evidence["cases"] == []
    assert evidence["operator"] == "test-operator"
    assert next(tmp_path.glob(f"*-{adapter}-commercial.md")).exists()


def test_open_with_validated_fabric_config_still_attempts_no_connection(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    approve(monkeypatch)
    monkeypatch.setenv("NS_G01A_FABRIC_HOST", FABRIC_HOST)
    monkeypatch.setenv("NS_G01A_FABRIC_DATABASE", "nsdemo")
    monkeypatch.setenv("NS_G01A_FABRIC_REGION", "eastus2")
    monkeypatch.setenv("NS_G01A_FABRIC_SKU_CLASS", "F2")
    assert load().main(["--adapter", "fabric", "--evidence-dir", str(tmp_path)]) == 3
    evidence = json.loads(next(tmp_path.glob("*-fabric-commercial.json")).read_text("utf-8"))
    assert evidence["region"] == "eastus2"
    assert evidence["backend_sku_class"] == "F2"
    assert FABRIC_HOST not in json.dumps(evidence)  # hosts are never written


def test_synapse_config_is_validated_when_supplied(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    approve(monkeypatch)
    monkeypatch.setenv("NS_G01A_SYNAPSE_WORKSPACE", "nsdemo")
    monkeypatch.setenv("NS_G01A_SYNAPSE_DATABASE", "nsanalytics")
    monkeypatch.setenv("NS_G01A_SYNAPSE_MODE", "dedicated")
    monkeypatch.setenv("NS_G01A_SYNAPSE_REGION", "eastus2")
    monkeypatch.setenv("NS_G01A_SYNAPSE_HOST", "nsdemo-ondemand.sql.azuresynapse.net")
    assert load().main(["--adapter", "synapse"]) == 2  # serverless host for a dedicated mode
    assert "configuration refused" in capsys.readouterr().err
