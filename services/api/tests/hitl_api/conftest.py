"""Import the PRP-06 authz harness and the shared action-plane harness (``../actions_api``)."""

import sys
from pathlib import Path

_TESTS = Path(__file__).resolve().parents[1]
for _path in (_TESTS, _TESTS / "actions_api"):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))
