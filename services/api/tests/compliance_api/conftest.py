"""Make the shared PRP-06 authz harness (``services/api/tests/authz``) importable from here."""

import sys
from pathlib import Path

_TESTS = Path(__file__).resolve().parents[1]
if str(_TESTS) not in sys.path:
    sys.path.insert(0, str(_TESTS))
