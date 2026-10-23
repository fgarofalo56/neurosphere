"""Make the DR scripts (``infra/dr``, a script directory, not a package) importable here."""

from __future__ import annotations

import sys
from pathlib import Path

DR_DIR = Path(__file__).resolve().parents[3] / "infra" / "dr"
if str(DR_DIR) not in sys.path:
    sys.path.insert(0, str(DR_DIR))
