"""G02 profile gates (AKS, App Service): every precondition refuses and writes nothing."""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import uuid
from collections.abc import Sequence
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[3]
GATES = REPO / "scripts" / "gates"
EVIDENCE = REPO / "docs" / "evidence" / "G02"
SCRIPTS = ("g02_profile_aks.py", "g02_profile_appservice.py")


def _load(name: str, file: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, GATES / file)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _common() -> ModuleType:
    if str(GATES) not in sys.path:
        sys.path.insert(0, str(GATES))
    return importlib.import_module("_g02_profile_common")


def _listing() -> set[str]:
    return {p.name for p in EVIDENCE.iterdir()} if EVIDENCE.exists() else set()


def _clean_env() -> dict[str, str]:
    return {k: v for k, v in os.environ.items() if not k.startswith("NS_")}


def _fake_az(tmp_path: Path, cloud: str) -> tuple[Path, Path]:
    """A fake `az` first on PATH that appends its argv to a log and answers `cloud show`."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = tmp_path / "calls.log"
    if os.name == "nt":
        (bin_dir / "az.cmd").write_text(
            f'@echo off\r\necho %*>>"{log}"\r\necho {cloud}\r\n', encoding="utf-8"
        )
    else:
        exe = bin_dir / "az"
        exe.write_text(f'#!/bin/sh\necho "$@" >> "{log}"\necho {cloud}\n', encoding="utf-8")
        exe.chmod(0o755)
    return bin_dir, log


def _run(script: str, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(GATES / script)],
        capture_output=True,
        text=True,
        env=env,
        timeout=120,
        check=False,
        cwd=REPO,
    )


@pytest.mark.parametrize("script", SCRIPTS)
@pytest.mark.parametrize("approval", [None, "0", ""])
def test_without_approval_refuses_open_and_writes_nothing(
    script: str, approval: str | None, tmp_path: Path
) -> None:
    bin_dir, log = _fake_az(tmp_path, "AzureUSGovernment")
    env = _clean_env()
    env["PATH"] = str(bin_dir) + os.pathsep + env.get("PATH", "")
    if approval is not None:
        env["NS_LIVE_APPROVED"] = approval
    before = _listing()
    proc = _run(script, env)
    assert proc.returncode == 2
    assert "OPEN" in proc.stdout
    assert _listing() == before
    assert not log.exists()


@pytest.mark.parametrize("script", SCRIPTS)
def test_approved_without_government_subscription_refuses_and_runs_no_az(
    script: str, tmp_path: Path
) -> None:
    bin_dir, log = _fake_az(tmp_path, "AzureUSGovernment")
    env = _clean_env()
    env["PATH"] = str(bin_dir) + os.pathsep + env.get("PATH", "")
    env["NS_LIVE_APPROVED"] = "1"
    before = _listing()
    proc = _run(script, env)
    assert proc.returncode == 2
    assert "OPEN" in proc.stdout
    assert "NS_GOV_SUBSCRIPTION_ID" in proc.stdout
    assert _listing() == before
    assert not log.exists()


@pytest.mark.parametrize("script", SCRIPTS)
def test_commercial_cloud_refuses_after_only_a_cloud_probe(script: str, tmp_path: Path) -> None:
    bin_dir, log = _fake_az(tmp_path, "AzureCloud")
    sub = str(uuid.uuid4())
    env = _clean_env()
    env["PATH"] = str(bin_dir) + os.pathsep + env.get("PATH", "")
    env["NS_LIVE_APPROVED"] = "1"
    env["NS_GOV_SUBSCRIPTION_ID"] = sub
    before = _listing()
    proc = _run(script, env)
    assert proc.returncode == 2
    assert "OPEN" in proc.stdout
    assert sub not in proc.stdout + proc.stderr
    assert _listing() == before
    lines = [ln.strip() for ln in log.read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert len(lines) == 1
    assert lines[0].startswith("cloud show")


class _Recorder:
    def __init__(self, cloud: str = "AzureUSGovernment") -> None:
        self.calls: list[list[str]] = []
        self.cloud = cloud
        self.run_id = ""

    def __call__(self, argv: Sequence[str]) -> Any:
        c = _common()
        self.calls.append(list(argv))
        a = list(argv)
        out: Any = ""
        if a[:3] == ["az", "cloud", "show"]:
            out = self.cloud + "\n"
        elif a[:3] == ["az", "group", "create"]:
            tags = a[a.index("--tags") + 1 :]
            self.run_id = next(t.split("=", 1)[1] for t in tags if t.startswith(c.TAG_RUN))
        elif a[:3] == ["az", "resource", "list"]:
            rid = "/subscriptions/x/resourceGroups/rg-ns-g02-appservice-" + self.run_id
            ids = [rid + "/providers/Microsoft.Web/sites/api"]
            if "[].id" in a:
                out = json.dumps(ids)
            else:
                tags = {c.TAG_RUN: self.run_id, c.TAG_CREATED_BY: "neurosphere"}
                out = json.dumps([{"id": i, "tags": tags} for i in ids])
        elif a[:3] == ["az", "webapp", "list"]:
            out = json.dumps([{"name": "api", "state": "Running"}])
        elif a[:4] == ["az", "deployment", "group", "what-if"]:
            out = json.dumps({"changes": [{"changeType": "NoChange"}, {"changeType": "Ignore"}]})
        elif a[:3] == ["az", "group", "show"]:
            out = json.dumps({c.TAG_RUN: self.run_id})
        return c.CmdResult(0, out, "")


def test_region_outside_government_set_refuses_before_any_az_call(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("NS_LIVE_APPROVED", "1")
    monkeypatch.setenv("NS_GOV_SUBSCRIPTION_ID", str(uuid.uuid4()))
    rec = _Recorder()
    mod = _load("g02_aks_region_under_test", "g02_profile_aks.py")
    assert mod.main(["--location", "eastus2"], runner=rec) == 2
    assert "OPEN" in capsys.readouterr().out
    assert rec.calls == []


def test_malformed_subscription_refuses_without_echoing_it(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("NS_LIVE_APPROVED", "1")
    monkeypatch.setenv("NS_GOV_SUBSCRIPTION_ID", "not-a-guid-value")
    rec = _Recorder()
    mod = _load("g02_aks_badsub_under_test", "g02_profile_aks.py")
    assert mod.main([], runner=rec) == 2
    captured = capsys.readouterr()
    assert "not-a-guid-value" not in captured.out + captured.err
    assert rec.calls == []


def test_commercial_cloud_in_process_runs_only_cloud_show(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("NS_LIVE_APPROVED", "1")
    monkeypatch.setenv("NS_GOV_SUBSCRIPTION_ID", str(uuid.uuid4()))
    rec = _Recorder(cloud="AzureCloud")
    mod = _load("g02_app_cloud_under_test", "g02_profile_appservice.py")
    assert mod.main([], runner=rec, evidence_dir=tmp_path / "ev") == 2
    assert rec.calls == [["az", "cloud", "show", "--query", "name", "-o", "tsv"]]
    assert not (tmp_path / "ev").exists()


def test_missing_image_registry_refuses_after_cloud_probe(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("NS_LIVE_APPROVED", "1")
    monkeypatch.setenv("NS_GOV_SUBSCRIPTION_ID", str(uuid.uuid4()))
    monkeypatch.delenv("NS_GOV_IMAGE_REGISTRY", raising=False)
    rec = _Recorder()
    mod = _load("g02_app_registry_under_test", "g02_profile_appservice.py")
    assert mod.main([], runner=rec, evidence_dir=tmp_path / "ev") == 2
    assert len(rec.calls) == 1
    assert not (tmp_path / "ev").exists()


def test_fully_faked_approved_path_passes_and_redacts_subscription(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    sub = str(uuid.uuid4())
    monkeypatch.setenv("NS_LIVE_APPROVED", "1")
    monkeypatch.setenv("NS_GOV_SUBSCRIPTION_ID", sub)
    monkeypatch.setenv("NS_GOV_IMAGE_REGISTRY", "registry.example.invalid")
    rec = _Recorder()
    mod = _load("g02_app_happy_under_test", "g02_profile_appservice.py")
    ev_dir = tmp_path / "ev"
    assert mod.main([], runner=rec, evidence_dir=ev_dir, work_dir=tmp_path) == 0
    written = list(ev_dir.iterdir())
    assert len(written) == 1
    assert written[0].name.startswith("profile-appservice-")
    text = written[0].read_text(encoding="utf-8")
    assert text.splitlines()[2].startswith("Live gate evidence only.")
    assert sub not in text
    assert ["az", "group", "delete"] == rec.calls[-1][:3]


def test_scrubber_fails_the_writer_on_credential_shaped_value(tmp_path: Path) -> None:
    c = _common()
    ev: dict[str, Any] = {
        "profile": "aks",
        "result": "PASS",
        "script_version": "1",
        "started_utc": "t",
        "finished_utc": "t",
        "cloud": "AzureUSGovernment",
        "location": "usgovvirginia",
        "subscription": "<subscription:abcd1234>",
        "resource_group": "rg",
        "drift_changes": 0,
        "dryrun_removable": 1,
        "dryrun_protected": 0,
        "teardown": "ok",
        "checks": [{"name": "x", "status": "PASS", "detail": "Account" + "Key=" + "abc"}],
    }
    with pytest.raises(c.ScrubError):
        c.write_evidence(ev, tmp_path / "ev", "")
    assert not (tmp_path / "ev").exists()


def test_rendered_evidence_never_contains_a_guid() -> None:
    c = _common()
    sub = str(uuid.uuid4())
    other = str(uuid.uuid4())
    ev: dict[str, Any] = {
        "profile": "aks",
        "result": "PASS",
        "script_version": "1",
        "started_utc": "t",
        "finished_utc": "t",
        "cloud": "AzureUSGovernment",
        "location": "usgovvirginia",
        "subscription": c.subscription_token(sub),
        "resource_group": "rg",
        "drift_changes": 0,
        "dryrun_removable": 1,
        "dryrun_protected": 0,
        "teardown": f"ok {sub}",
        "checks": [{"name": "x", "status": "PASS", "detail": f"/subscriptions/{other}/x"}],
    }
    text = c.render_evidence(ev, sub)
    assert sub not in text
    assert other not in text
    assert "Live gate evidence only. Availability is not authorization" in text


def test_uninstall_dry_run_excludes_shared_and_untagged_resources() -> None:
    c = _common()
    rg, run = "rg-ns-g02-aks-abc", "abc"
    mine = {c.TAG_RUN: run, c.TAG_CREATED_BY: "neurosphere"}
    base = f"/subscriptions/{uuid.uuid4()}/resourceGroups"
    own = f"{base}/{rg}/providers/Microsoft.KeyVault/vaults/kv"
    shared_untagged = f"{base}/{rg}/providers/Microsoft.Storage/storageAccounts/shared"
    shared_other_rg = f"{base}/rg-shared/providers/Microsoft.DocumentDB/databaseAccounts/cosmos"
    other_run = f"{base}/{rg}/providers/Microsoft.Search/searchServices/s"
    plan = c.plan_dry_run(
        [
            {"id": own, "tags": mine},
            {"id": shared_untagged, "tags": None},
            {"id": shared_other_rg, "tags": mine},
            {"id": other_run, "tags": {c.TAG_RUN: "zzz", c.TAG_CREATED_BY: "neurosphere"}},
        ],
        rg,
        run,
    )
    assert plan.removable == (own,)
    assert set(plan.protected) == {shared_untagged, shared_other_rg, other_run}
