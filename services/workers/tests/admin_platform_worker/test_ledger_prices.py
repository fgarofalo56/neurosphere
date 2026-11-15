"""PRP-44 item 5: the ingestion ledger price table from stored snapshots plus the file table."""

from __future__ import annotations

import json
import logging
from datetime import date
from pathlib import Path

import pytest
from neurosphere_core.admin.platform import PriceVersionConflictError
from neurosphere_workers.admin_platform import PRICE_STORE_UNAVAILABLE, ledger_price_table
from neurosphere_workers.admin_platform import prices as module

from .support import file_version, runtime_config, snapshot


def _write_file_table(tmp_path: Path, *versions: object) -> Path:
    path = tmp_path / "prices.json"
    path.write_text(
        json.dumps({"versions": [json.loads(v.model_dump_json()) for v in versions]}),  # type: ignore[attr-defined]
        encoding="utf-8",
    )
    return path


def _stub(monkeypatch: pytest.MonkeyPatch, snapshots: list[object] | Exception) -> None:
    async def fake(cfg: object) -> list[object]:
        if isinstance(snapshots, Exception):
            raise snapshots
        return snapshots

    monkeypatch.setattr(module, "list_stored_snapshots", fake)


async def test_a_stored_snapshot_prices_an_estimate_without_a_file(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub(monkeypatch, [snapshot()])
    table = await ledger_price_table(runtime_config())
    estimate = table.resolve("azure_openai", "gpt-4.1", None, date(2026, 11, 5))
    assert estimate is not None and estimate.version.price_version_id == "aoai-2026-11"


async def test_stored_snapshots_merge_with_the_file_table(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _stub(monkeypatch, [snapshot()])
    path = _write_file_table(tmp_path, file_version("file-1"))
    table = await ledger_price_table(runtime_config(), path)
    assert {v.price_version_id for v in table.versions} == {"file-1", "aoai-2026-11"}


async def test_equal_id_and_content_collapses(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    stored = snapshot()
    _stub(monkeypatch, [stored])
    path = _write_file_table(tmp_path, stored.to_price_version())
    table = await ledger_price_table(runtime_config(), path)
    assert [v.price_version_id for v in table.versions] == ["aoai-2026-11"]


async def test_equal_id_with_different_content_refuses_startup(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _stub(monkeypatch, [snapshot()])
    path = _write_file_table(tmp_path, file_version("aoai-2026-11", "gpt-4.1", "7.77"))
    with pytest.raises(PriceVersionConflictError) as caught:
        await ledger_price_table(runtime_config(), path)
    assert caught.value.reason == "price_version_conflict"


async def test_nothing_stored_behaves_exactly_as_before(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _stub(monkeypatch, [])
    assert (await ledger_price_table(runtime_config())).versions == []
    path = _write_file_table(tmp_path, file_version("file-1"))
    table = await ledger_price_table(runtime_config(), path)
    assert [v.price_version_id for v in table.versions] == ["file-1"]


async def test_a_store_failure_falls_back_to_the_file_with_one_reason_coded_line(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    _stub(monkeypatch, RuntimeError("cosmos down 2.50"))
    path = _write_file_table(tmp_path, file_version("file-1"))
    with caplog.at_level(logging.INFO, logger="neurosphere_workers.admin_platform"):
        table = await ledger_price_table(runtime_config(), path)
    assert [v.price_version_id for v in table.versions] == ["file-1"]
    lines = [r for r in caplog.records if getattr(r, "reason", None) == PRICE_STORE_UNAVAILABLE]
    assert len(lines) == 1
    assert "2.50" not in caplog.text and "cosmos down" not in caplog.text


async def test_the_resolved_table_is_logged_by_count_never_by_price(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    _stub(monkeypatch, [snapshot(input_price="2.50")])
    with caplog.at_level(logging.INFO, logger="neurosphere_workers.admin_platform"):
        await ledger_price_table(runtime_config())
    assert "2.50" not in caplog.text and "10.00" not in caplog.text
