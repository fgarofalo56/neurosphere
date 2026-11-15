"""PRP-42 item 2: the bounded stored-config loader."""

from __future__ import annotations

import asyncio
import logging

import pytest
from neurosphere_workers.connector_config import load_stored_config

from .support import CUSTOMER, billing, gateway, repo, store


async def test_returns_the_stored_config_of_the_kind() -> None:
    repository = repo()
    await store(repository, gateway())
    await store(repository, billing())
    found = await load_stored_config(repository, CUSTOMER, "billing_export", timeout_seconds=1)
    assert found is not None and found.connector_kind == "billing_export"
    assert await load_stored_config(repository, CUSTOMER, "otel", timeout_seconds=1) is None


async def test_other_customers_configs_are_invisible() -> None:
    repository = repo()
    await store(repository, gateway())
    assert (
        await load_stored_config(repository, "fabrikam", "gateway_poll", timeout_seconds=1) is None
    )


async def test_store_failure_is_one_log_line_with_reason_and_never_raises(
    caplog: pytest.LogCaptureFixture,
) -> None:
    repository = repo()
    repository.fail_with(RuntimeError("cosmos down: https://secret-host"))
    with caplog.at_level(logging.INFO):
        assert (
            await load_stored_config(repository, CUSTOMER, "gateway_poll", timeout_seconds=1)
            is None
        )
    lines = [
        r
        for r in caplog.records
        if getattr(r, "event", "") == "worker.connector_config_store_unavailable"
    ]
    assert len(lines) == 1 and lines[0].reason == "connector_config_store_unavailable"  # type: ignore[attr-defined]
    assert "secret-host" not in caplog.text


async def test_slow_store_is_bounded_by_the_timeout() -> None:
    repository = repo()

    async def slow(*args: object, **kwargs: object) -> list[object]:
        await asyncio.sleep(5)
        return []

    repository.list_by_kind = slow  # type: ignore[method-assign]
    assert (
        await load_stored_config(repository, CUSTOMER, "gateway_poll", timeout_seconds=0.05) is None
    )
