"""Make the shared PRP-06 / PRP-17 / PRP-19 test harnesses importable here.

``services/api/tests/authz`` (dev-issuer tokens, in-memory policy), ``.../actions_api`` (the
PRP-17 action plane), ``.../copilot_api`` (scripted ports, SSE parser) and ``.../reports`` (report
bodies) have no installable package, so their directories go on ``sys.path``. Only the path is
arranged; no compose fixture is imported here, so the unmarked ``test_wiring.py`` never touches
docker.
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
