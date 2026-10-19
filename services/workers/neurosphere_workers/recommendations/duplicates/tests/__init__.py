"""Tests of the duplicate-candidate job.

The sandbox generator lives at the repository root (it is not an installed package), so the
root is put on ``sys.path`` before any test module imports ``sandbox``.
"""

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[6]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
