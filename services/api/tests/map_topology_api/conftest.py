"""Make the map harness (``services/api/tests/map``) and the PRP-06 authz harness importable.

Neither this directory nor ``services/api/tests/map`` has an ``__init__.py`` (the map suite's
convention), so the paths are put on ``sys.path`` explicitly. The directory name is unique on
purpose: same-named test packages shadow each other inside one pytest session.
"""

import sys
from pathlib import Path

_API_TESTS = Path(__file__).resolve().parents[1]
for _path in (_API_TESTS, _API_TESTS / "map"):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))
