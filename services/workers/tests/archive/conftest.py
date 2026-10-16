from __future__ import annotations

import pytest

from .support import Doc, FakeContainer, rich_telemetry, sandbox_docs


@pytest.fixture
def template() -> Doc:
    return rich_telemetry()


@pytest.fixture
def container() -> FakeContainer:
    return FakeContainer()


@pytest.fixture(scope="session")
def sandbox_telemetry() -> list[Doc]:
    return sandbox_docs()
