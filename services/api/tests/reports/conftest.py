"""Make the shared PRP-06 authz harness (``services/api/tests/authz``) importable from here."""

import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
for _path in (_HERE.parent, _HERE):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))
