"""Evidence entry point: ``python -m neurosphere_api.finops`` (run from the repository root).

Generates a deterministic month of SYNTHETIC sandbox cost records into the in-memory ledger,
forecasts the second half of the month from the first (a backtest: the actuals are known), and
writes forecast-versus-actual rows to ``docs/evidence/G07/finops/``. No network, no paid call, no
production data.
"""

import argparse
import asyncio
import sys
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Final

from neurosphere_api.finops.evidence import build_evidence, write_evidence
from neurosphere_api.finops.sandbox_source import SEED, load_sandbox_ledger
from neurosphere_api.finops.service import build_forecast

ENVIRONMENT: Final = "sandbox in-memory ledger, synthetic data"
DEFAULT_OUT: Final = Path("docs/evidence/G07/finops/forecast-vs-actual-sandbox.json")
DEFAULT_AS_OF: Final = date(2026, 10, 18)
SANDBOX_TODAY: Final = date(2026, 11, 1)  # the day after the synthetic month: all actuals known


async def run(out: Path, seed: int, as_of: date, history_days: int, horizon_days: int) -> Path:
    sandbox = await load_sandbox_ledger(seed)
    domain_id = sandbox.domain_ids[0]
    response = await build_forecast(
        sandbox.store,
        customer_id=sandbox.customer_id,
        domain_id=domain_id,
        as_of=as_of,
        today=SANDBOX_TODAY,
        history_days=history_days,
        horizon_days=horizon_days,
    )
    evidence = build_evidence(
        response,
        environment=ENVIRONMENT,
        generated_on=datetime.now(UTC).date(),
        currency="USD",
        data_description=(
            f"sandbox generator seed {seed}, {sandbox.record_count} synthetic cost records, "
            f"customer {sandbox.customer_id}, first domain of {len(sandbox.domain_ids)}"
        ),
    )
    write_evidence(out, evidence)
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m neurosphere_api.finops", description=__doc__)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--seed", type=int, default=SEED)
    parser.add_argument("--as-of", type=date.fromisoformat, default=DEFAULT_AS_OF)
    parser.add_argument("--history-days", type=int, default=17)
    parser.add_argument("--horizon-days", type=int, default=14)
    args = parser.parse_args(argv)
    written = asyncio.run(
        run(args.out, args.seed, args.as_of, args.history_days, args.horizon_days)
    )
    sys.stdout.write(f"wrote {written}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
