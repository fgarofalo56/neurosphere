"""Make the shared PRP-06 authz harness (``services/api/tests/authz``) importable here.

Only paths are arranged; the end-to-end test is in process and needs no compose service.
"""

from __future__ import annotations

import sys
from pathlib import Path

_API_TESTS = Path(__file__).resolve().parents[3] / "api" / "tests"
if str(_API_TESTS) not in sys.path:
    sys.path.insert(0, str(_API_TESTS))
