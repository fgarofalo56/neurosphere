"""Make the shared PRP-06 authz harness (``services/api/tests/authz``) and the sandbox generator
importable here. Only paths are arranged; this suite is in-process and needs no compose service."""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]
for _path in (_ROOT / "services" / "api" / "tests", _ROOT):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))
