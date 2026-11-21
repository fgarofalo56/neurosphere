"""Make the shared API test packages (``authz``, ``ui_adapters_api``) importable from here."""

import sys
from pathlib import Path

_TESTS = Path(__file__).resolve().parents[1]
if str(_TESTS) not in sys.path:
    sys.path.insert(0, str(_TESTS))
