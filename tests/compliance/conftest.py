"""Fixtures that load the compliance scripts by path (scripts/ is not a package)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _load(name: str) -> ModuleType:
    path = ROOT / "scripts" / "compliance" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"_ns_compliance_{name}", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclasses need the module registered
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="session")
def collector() -> ModuleType:
    return _load("collect_evidence")


@pytest.fixture(scope="session")
def checker() -> ModuleType:
    return _load("check_statements")


@pytest.fixture(scope="session")
def repo_root() -> Path:
    return ROOT
