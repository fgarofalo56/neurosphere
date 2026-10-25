"""Load the CI conformance suites by path so the emulator runs the SAME assertions.

``packages/core/tests/{hitl_cosmos,review_queue_cosmos,lifecycle_cosmos}/contract.py`` are
self-contained modules (no sibling imports). They are loaded under private module names so they
cannot shadow, or be shadowed by, the CI test packages of the same directory names.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

_CORE_TESTS = Path(__file__).resolve().parents[3] / "packages" / "core" / "tests"


def load_contract(package: str) -> ModuleType:
    name = f"stores_hitl_contract_{package}"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, _CORE_TESTS / package / "contract.py")
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module
