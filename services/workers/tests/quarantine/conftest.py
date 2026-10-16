"""Fixtures for the quarantine tests (the ingestion fixtures are not visible from here)."""

from __future__ import annotations

import pytest

from .support import Doc as Doc
from .support import FakeBlobContainer, Harness, rich_telemetry


@pytest.fixture
def template() -> Doc:
    return rich_telemetry()


@pytest.fixture
def harness() -> Harness:
    return Harness()


@pytest.fixture
def container() -> FakeBlobContainer:
    return FakeBlobContainer()
