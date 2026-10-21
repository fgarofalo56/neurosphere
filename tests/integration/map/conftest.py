"""Make the shared PRP-06 authz harness and the PRP-18 unit-test helpers importable here.

``services/api/tests/authz`` (dev-issuer tokens, in-memory policy), ``.../map`` (catalog seeding
helpers) and ``.../replay`` (span builders) have no installable package, so their directories go on
``sys.path``. Only the path is arranged; no compose fixture is imported here, so the unmarked
``test_wiring.py`` never touches docker.
"""

from __future__ import annotations

import sys
from pathlib import Path

_API_TESTS = Path(__file__).resolve().parents[3] / "services" / "api" / "tests"
for _path in (_API_TESTS, _API_TESTS / "map", _API_TESTS / "replay"):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))
