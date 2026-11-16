"""PRP-51: sbx_grant_operator.py refuses ``--cloud government`` (Commercial-only seed)."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "sandbox" / "sbx_grant_operator.py"
FAKE_OID = "55555555-5555-4555-8555-555555555555"
FAKE_TENANT = "22222222-2222-4222-8222-222222222222"


def _load():
    spec = importlib.util.spec_from_file_location("sbx_grant_operator_cloud_test", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_government_cloud_is_refused_with_one_line(capsys: pytest.CaptureFixture[str]) -> None:
    mod = _load()
    code = mod.main(
        [
            "--object-id",
            FAKE_OID,
            "--role",
            "admin",
            "--tenant-id",
            FAKE_TENANT,
            "--cloud",
            "government",
        ],
        env={},
    )
    assert code == mod.EXIT_REFUSED
    err = capsys.readouterr().err.strip().splitlines()
    assert len(err) == 1
    assert "Commercial-only" in err[0]
