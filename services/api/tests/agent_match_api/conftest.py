"""Make the shared PRP-06 authz harness (``services/api/tests/authz``) and the matcher test
helpers (``packages/core/tests/agent_match``) importable from here."""

import sys
from pathlib import Path

_API_TESTS = Path(__file__).resolve().parents[1]
_CORE_TESTS = Path(__file__).resolve().parents[4] / "packages" / "core" / "tests"
for _path in (_API_TESTS, _CORE_TESTS):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))
