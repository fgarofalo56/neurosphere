"""Make the copilot harnesses importable from here (no ``__init__.py`` in these test dirs).

Same path set as ``services/api/tests/copilot_api/conftest.py``: the shared copilot, action-plane
and authz harnesses are imported by module name. Fixtures of this directory are prefixed
``tools_``.
"""

import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_API_TESTS = _HERE.parent
_REPO_TESTS = _HERE.parents[3] / "tests"
for _path in (
    _REPO_TESTS,
    _API_TESTS / "actions_api",
    _API_TESTS / "reports",
    _API_TESTS,
    _API_TESTS / "copilot_api",
):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))
