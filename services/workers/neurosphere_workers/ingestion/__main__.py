"""``python -m neurosphere_workers.ingestion``: alias for ``NS_WORKER_ROLES=ingestion``.

The normalizer consumer now runs through the one runtime entrypoint (same supervised role, same
health endpoints), so this module only selects the role. Sinks and stores are still built by
``wiring.build_pipeline_deps`` (the path the quarantine replay CLI also uses); infrastructure is
auto-created only when NS_ENV=local.
"""

from __future__ import annotations

import sys

from neurosphere_workers.runtime.__main__ import main as runtime_main

ROLE = "ingestion"


def main() -> int:
    return runtime_main(ROLE)


if __name__ == "__main__":
    sys.exit(main())
