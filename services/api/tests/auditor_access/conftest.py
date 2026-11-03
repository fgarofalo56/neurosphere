"""Make the shared authz harness and the action-plane harness importable by module name.

This directory has no ``__init__.py`` (same convention as ``services/api/tests/actions_api``).
"""

import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_TESTS = _HERE.parent
for _path in (_TESTS, _TESTS / "actions_api"):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))
