"""Make the shared PRP-06 authz harness (``services/api/tests/authz``) importable here.

Only paths are arranged; the in-process slice needs no compose service. The Cosmos emulator test
(``test_intent_store_cosmos.py``) keeps its own ``integration`` marker and is unaffected.
"""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]
for _path in (_ROOT / "services" / "api" / "tests", _ROOT):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))
