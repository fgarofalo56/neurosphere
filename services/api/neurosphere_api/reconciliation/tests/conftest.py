"""Make the shared PRP-06 authz harness (``services/api/tests/authz``) importable by name."""

from __future__ import annotations

import sys
from pathlib import Path

_API_TESTS = str(Path(__file__).resolve().parents[3] / "tests")
if _API_TESTS not in sys.path:
    sys.path.append(_API_TESTS)
