"""PRP-44 item 5: ``build_ingestion`` hands the merged price table to the pipeline deps."""

from __future__ import annotations

from typing import Any

import pytest
from neurosphere_core.clients import ClientLifetime
from neurosphere_workers.admin_platform import prices as prices_module
from neurosphere_workers.runtime import factories

from .support import runtime_config, snapshot


class _StopError(Exception):
    pass


async def test_build_ingestion_passes_the_snapshot_price_table(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def stored(cfg: object) -> list[object]:
        return [snapshot()]

    seen: dict[str, Any] = {}

    async def fake_deps(*_: object, **kwargs: Any) -> object:
        seen.update(kwargs)
        raise _StopError

    monkeypatch.setattr(prices_module, "list_stored_snapshots", stored)
    monkeypatch.setattr(factories, "build_pipeline_deps", fake_deps)
    with pytest.raises(_StopError):
        await factories.build_ingestion(runtime_config(), ClientLifetime())
    table = seen["price_table"]
    assert [v.price_version_id for v in table.versions] == ["aoai-2026-11"]
