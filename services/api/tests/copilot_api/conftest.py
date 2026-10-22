"""Make the shared harnesses importable from here (no ``__init__.py`` in these test dirs).

* ``services/api/tests`` -- the PRP-06 authz harness (``authz.authz_helpers``);
* ``services/api/tests/actions_api`` -- the PRP-17 action-plane harness;
* ``tests`` (repo root) -- the PRP-12 injection corpus (``security.injection``).
"""

import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_API_TESTS = _HERE.parent
_REPO_TESTS = _HERE.parents[3] / "tests"
for _path in (_REPO_TESTS, _API_TESTS / "actions_api", _API_TESTS, _HERE):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))
