"""Make the PRP-06 authz harness and the gateway API harnesses importable from here."""

import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
for _path in (_HERE.parent / "gateway_api", _HERE.parent, _HERE):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))
