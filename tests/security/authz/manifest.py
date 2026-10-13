"""Print a ledger skeleton for ``case_manifest.json`` (never overwrites the committed file).

``PYTHONPATH=tests python -m security.authz.manifest``
"""

import json
from typing import Any

from .cases import CASES, KINDS


def skeleton() -> dict[str, Any]:
    ids = {k: sorted(r.id for r in CASES[k]) for k in KINDS}
    return {"counts": {k: len(v) for k, v in ids.items()}, "ids": ids, "removed": {}}


if __name__ == "__main__":
    print(json.dumps(skeleton(), indent=1))
