"""Session fixtures: generate each data set once and share it across test modules."""

from __future__ import annotations

from pathlib import Path

import pytest

from sandbox.config import PROFILES, BadEventRates, GenerateConfig
from sandbox.generate import generate


def make_config(
    seed: int = 1,
    profile: str = "tiny",
    cloud: str = "commercial",
    rates: BadEventRates | None = None,
) -> GenerateConfig:
    return GenerateConfig(
        seed=seed,
        profile=PROFILES[profile],
        cloud=cloud,
        rates=rates or BadEventRates(),
    )


@pytest.fixture(scope="session")
def tiny_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    out = tmp_path_factory.mktemp("tiny")
    generate(make_config(), out)
    return out


@pytest.fixture(scope="session")
def pilot_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    out = tmp_path_factory.mktemp("pilot")
    generate(make_config(profile="pilot"), out)
    return out
