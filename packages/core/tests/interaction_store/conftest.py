from __future__ import annotations

from pathlib import Path

import pytest
from neurosphere_core.crypto import LocalFileKeyWrapper
from neurosphere_core.interactions import InMemoryInteractionStore
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader

from ._support import KEK_URI, policy


@pytest.fixture
def local_wrapper(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> LocalFileKeyWrapper:
    monkeypatch.setenv("NS_ENV", "local")
    return LocalFileKeyWrapper(tmp_path / "interaction-kek.bin")


@pytest.fixture
def metric_reader() -> InMemoryMetricReader:
    return InMemoryMetricReader()


@pytest.fixture
def store(
    local_wrapper: LocalFileKeyWrapper, metric_reader: InMemoryMetricReader
) -> InMemoryInteractionStore:
    meter = MeterProvider(metric_readers=[metric_reader]).get_meter("test")
    return InMemoryInteractionStore(local_wrapper, kek_uri=KEK_URI, policy=policy(), meter=meter)
