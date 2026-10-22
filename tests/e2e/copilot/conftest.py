"""Make the shared PRP-06 / PRP-17 / PRP-19 test harnesses importable here.

Same arrangement as ``tests/integration/copilot/conftest.py``: the harness directories under
``services/api/tests`` have no installable package, so only their paths go on ``sys.path``.
No compose fixture is imported, so the first-token test never touches docker.
"""

from __future__ import annotations

import sys
from pathlib import Path

_API_TESTS = Path(__file__).resolve().parents[3] / "services" / "api" / "tests"
for _path in (
    _API_TESTS,
    _API_TESTS / "actions_api",
    _API_TESTS / "copilot_api",
    _API_TESTS / "reports",
):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))
