"""Fixtures for the shared injection corpus suite (PRP-12 item 4)."""

import pytest

from .schema import InjectionCase, load_corpus


@pytest.fixture(scope="session")
def corpus() -> tuple[InjectionCase, ...]:
    return load_corpus()
