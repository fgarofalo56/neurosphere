"""Make the shared PRP-06 authz harness (``services/api/tests/authz``) importable from here.

``services/api/tests/map`` has no ``__init__.py``, so the tests directory is put on ``sys.path``
explicitly rather than relying on the order pytest collects other directories in.
"""

import sys
from pathlib import Path

_API_TESTS = Path(__file__).resolve().parents[1]
if str(_API_TESTS) not in sys.path:
    sys.path.insert(0, str(_API_TESTS))
