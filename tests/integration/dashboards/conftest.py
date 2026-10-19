"""Make the shared PRP-06 authz harness (``services/api/tests/authz``) importable here.

Only the path is arranged. The compose fixtures (``fresh_hub``, ``sandbox_dir``) are imported by
``test_vertical_slice.py`` itself, so the unmarked registration test never touches docker.
"""

from __future__ import annotations

import sys
from pathlib import Path

_API_TESTS = Path(__file__).resolve().parents[3] / "services" / "api" / "tests"
if str(_API_TESTS) not in sys.path:
    sys.path.insert(0, str(_API_TESTS))
