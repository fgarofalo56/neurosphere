"""G01 analytics gate: evidence hygiene (whitelisted fields, scrubber that fails the run)."""

from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path
from types import ModuleType

import pytest

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "gates" / "g01_analytics_live.py"
FAKE_JWT = "eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJ4In0.c2lnbmF0dXJl"
SECRETS = [
    FAKE_JWT,
    "AccountKey=QUJDREVGR0hJSktMTU5PUFFSU1RVVldYWVowMTIzNDU2Nzg5YWJjZGVm==",
    "Bearer abcdefghijklmnop0123456789",
    "dapi" + "0123456789abcdef0123456789abcdef",
    "password=hunter2",
]


def load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("g01_analytics_ev_under_test", SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["g01_analytics_ev_under_test"] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(autouse=True)
def _env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in list(os.environ):
        if key.startswith("NS_G01A_"):
            monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("NS_LIVE_APPROVED", "1")


@pytest.mark.parametrize("secret", SECRETS)
def test_scrubber_rejects_credential_shapes_in_values(secret: str) -> None:
    mod = load()
    with pytest.raises(mod.ScrubError):
        mod.scrub({"reason": f"failed with {secret}"})
    with pytest.raises(mod.ScrubError):
        mod.scrub({"cases": [{"error": secret}]})


@pytest.mark.parametrize("key", ["access_token", "client_secret", "api_key", "pat", "bearer"])
def test_scrubber_rejects_credential_shaped_keys(key: str) -> None:
    mod = load()
    with pytest.raises(mod.ScrubError):
        mod.scrub({key: "x"})


def test_scrubber_accepts_ordinary_evidence() -> None:
    load().scrub({"status": "PASS", "reason": "all cases passed", "region": "eastus2"})


@pytest.mark.parametrize("secret", SECRETS)
def test_a_credential_in_a_result_fails_the_run_and_writes_nothing(
    secret: str, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    mod = load()

    async def leaky(settings: object, options: object):
        return mod.AdapterResult(status="PASS", reason=f"ok {secret}")

    code = mod.main(
        ["--adapter", "fabric", "--evidence-dir", str(tmp_path)], runners={"fabric": leaky}
    )
    assert code == 1
    assert list(tmp_path.glob("*")) == []
    err = capsys.readouterr().err
    assert "evidence not written" in err
    assert secret not in err


def test_open_evidence_has_required_fields_and_label(tmp_path: Path) -> None:
    mod = load()
    assert mod.main(["--adapter", "synapse", "--evidence-dir", str(tmp_path)]) == 3
    path = next(tmp_path.glob("*-synapse-commercial.json"))
    evidence = json.loads(path.read_text(encoding="utf-8"))
    for required in (
        "gate",
        "adapter",
        "cloud",
        "status",
        "reason",
        "backend_sku_class",
        "region",
        "date",
        "operator",
        "data",
        "claim_boundary",
        "tolerance",
        "cases",
        "stub_delta_g12",
        "teardown",
    ):
        assert required in evidence, required
    assert evidence["gate"] == "G01"
    assert evidence["cloud"] == "commercial"
    assert "synthetic" in evidence["data"]
    assert "not an ATO" in evidence["claim_boundary"]
    assert path.name[:10] == evidence["date"]
    assert path.with_suffix(".md").read_text(encoding="utf-8").startswith("# G01 analytics")


def test_evidence_is_whitelisted_not_a_passthrough() -> None:
    mod = load()
    settings = mod.AdapterSettings(
        name="databricks",
        region="eastus2",
        sku_class="serverless",
        config={"host": "adb-1.7.azuredatabricks.net", "warehouse_id": "0123456789abcdef"},
    )
    options = mod.RunOptions(operator="op", keep=False, run_id="abc")
    result = mod.AdapterResult(status="PASS", reason="all cases passed")
    evidence = mod.build_evidence(settings, options, result, when=mod._utcnow())
    blob = json.dumps(evidence)
    assert "adb-1.7" not in blob  # host
    assert "0123456789abcdef" not in blob  # warehouse id
    mod.scrub(evidence)


def test_operator_label_that_looks_like_a_credential_is_refused(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = load().main(
        ["--adapter", "fabric", "--operator", FAKE_JWT, "--evidence-dir", str(tmp_path)]
    )
    assert code == 2
    assert list(tmp_path.glob("*")) == []
    assert FAKE_JWT not in capsys.readouterr().err


def test_second_run_same_day_does_not_overwrite(tmp_path: Path) -> None:
    mod = load()
    assert mod.main(["--adapter", "fabric", "--evidence-dir", str(tmp_path)]) == 3
    assert mod.main(["--adapter", "fabric", "--evidence-dir", str(tmp_path)]) == 3
    assert len(list(tmp_path.glob("*.json"))) == 2
