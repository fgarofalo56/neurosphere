"""scripts/connectors/billing_variance.py: offline report, confined paths (synthetic data)."""

from __future__ import annotations

import gzip
import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[3]
HEADER = "Date,CostInBillingCurrency,BillingCurrencyCode,ResourceId,MeterId\n"


def _load() -> ModuleType:
    path = ROOT / "scripts" / "connectors" / "billing_variance.py"
    spec = importlib.util.spec_from_file_location("_ns_billing_variance_cli", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


cli = _load()


def _write(root: Path) -> None:
    (root / "export").mkdir()
    (root / "export" / "p0.csv").write_text(
        HEADER + "2026-10-10,10.00,USD,/R1,m1\n2026-10-10,5.00,USD,/R1,m2\n,3.00,USD,/R1,m1\n",
        encoding="utf-8",
    )
    (root / "export" / "p1.csv.gz").write_bytes(
        gzip.compress((HEADER + "2026-10-11,,USD,/R1,m1\n").encode())
    )
    (root / "est.json").write_text(
        json.dumps(
            [
                {
                    "usage_date": "2026-10-10",
                    "resource_id": "/r1",
                    "currency": "USD",
                    "amount": "12",
                },
                {
                    "usage_date": "2026-10-11",
                    "resource_id": "/r1",
                    "currency": "USD",
                    "amount": "4",
                },
            ]
        ),
        encoding="utf-8",
    )


def test_report_is_printed_with_granularity_statement(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _write(tmp_path)
    code = cli.main(["--input-dir", str(tmp_path), "--export", "export", "--estimates", "est.json"])
    assert code == 0
    report = json.loads(capsys.readouterr().out)
    assert "Nothing is apportioned below the billing granularity" in report["granularity_statement"]
    assert report["billing_rows_without_date"] == 1  # dateless row surfaced, not hidden
    by_day = {line["usage_date"]: line for line in report["lines"]}
    assert by_day["2026-10-10"]["variance"] == "3.00"  # 15.00 billed - 12 estimated
    assert by_day["2026-10-11"]["status"] == "billing_unknown"  # blank cost: unknown, not 0
    assert by_day["2026-10-11"]["variance"] is None


def test_single_file_and_day_level(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _write(tmp_path)
    code = cli.main(
        [
            "--input-dir",
            str(tmp_path),
            "--export",
            "export/p0.csv",
            "--estimates",
            "est.json",
            "--level",
            "day",
        ]
    )
    assert code == 0
    assert json.loads(capsys.readouterr().out)["comparison_level"] == "day"


@pytest.mark.parametrize("bad", ["../outside.json", "export/../../outside.json"])
def test_traversal_outside_input_dir_is_refused(
    tmp_path: Path, bad: str, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / "in"
    root.mkdir()
    _write(root)
    (tmp_path / "outside.json").write_text("[]", encoding="utf-8")
    assert cli.main(["--input-dir", str(root), "--export", "export", "--estimates", bad]) == 2
    assert "refused" in capsys.readouterr().err
    assert cli.main(["--input-dir", str(root), "--export", bad, "--estimates", "est.json"]) == 2


def test_absolute_path_outside_input_dir_is_refused(tmp_path: Path) -> None:
    root = tmp_path / "in"
    root.mkdir()
    _write(root)
    outside = tmp_path / "outside.json"
    outside.write_text("[]", encoding="utf-8")
    argv = ["--input-dir", str(root), "--export", "export", "--estimates", str(outside)]
    assert cli.main(argv) == 2


def test_malformed_estimates_are_refused(tmp_path: Path) -> None:
    _write(tmp_path)
    (tmp_path / "est.json").write_text('{"not": "a list"}', encoding="utf-8")
    argv = ["--input-dir", str(tmp_path), "--export", "export", "--estimates", "est.json"]
    assert cli.main(argv) == 2
    (tmp_path / "est.json").write_text("not json", encoding="utf-8")
    assert cli.main(argv) == 2


def test_cli_makes_no_network_calls(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import socket

    def _no(*_a: object, **_k: object) -> None:
        raise AssertionError("network used")

    monkeypatch.setattr(socket, "socket", _no)
    _write(tmp_path)
    argv = ["--input-dir", str(tmp_path), "--export", "export", "--estimates", "est.json"]
    assert cli.main(argv) == 0
