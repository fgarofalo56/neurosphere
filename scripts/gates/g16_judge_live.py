"""G16 live judge run (PRP-16 item 2): an optional, operator-approved paid judge call.

Refuses unless NS_LIVE_APPROVED=1. The check is the first statement of ``main`` and runs before
any project, azure or network import: this module imports only ``os`` and ``sys``.

Status: the live run is OPEN. No model-inference SDK (Azure AI Inference, OpenAI, Foundry agents)
is a dependency of this repository, and adding one needs an ADR-0002 stack-pin row and operator
approval. Until then, even with NS_LIVE_APPROVED=1 this script makes no call and reports the live
run OPEN with that reason. A script that did not run a judge is not evidence.

How a live run would work once an adapter exists: build a ``Judge`` over the approved Foundry
deployment in the selected cloud (Entra / managed identity only, no key from arguments or
environment), run ``EvaluationService.run_offline`` over the SYNTHETIC pilot dataset with a small
``BudgetLedger`` (the same pre-call guard and budgets as CI), then write whitelisted fields only
(counts, tokens, cost with price_version, judge config version) to docs/evidence/G16/.

Exit codes: 2 REFUSED (approval missing; nothing was run); 3 OPEN (approved, but no adapter, so
nothing was run). It never exits 0: a pass requires a real judge call.
"""

from __future__ import annotations

import os
import sys

OPEN_REASON = (
    "no model-inference SDK is a repository dependency; a live judge adapter needs an ADR-0002 "
    "stack-pin row and operator approval"
)


def main() -> int:
    if os.environ.get("NS_LIVE_APPROVED") != "1":
        print(
            "REFUSED: g16_judge_live.py would make a paid judge call and needs operator approval; "
            "set NS_LIVE_APPROVED=1. No connection was attempted.",
            file=sys.stderr,
        )
        return 2
    print(f"OPEN: G16 live judge run did not run: {OPEN_REASON}.")
    return 3


if __name__ == "__main__":
    sys.exit(main())
