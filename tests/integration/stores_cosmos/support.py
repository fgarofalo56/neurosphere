"""Loader for the conformance modules shared with ``packages/core/tests/*_cosmos``."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

_TESTS = Path(__file__).resolve().parents[3] / "packages" / "core" / "tests"


def load_conformance(package: str) -> ModuleType:
    """Import ``packages/core/tests/<package>/conformance.py`` under a unique module name."""
    path = _TESTS / package / "conformance.py"
    name = f"stores_cosmos_conformance_{package}"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module
