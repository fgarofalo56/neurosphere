"""Run the benchmark against the compose Cosmos emulator and write docs/evidence/G03/.

docker compose up -d --wait cosmos
python tests/load/graph_benchmark/run_emulator.py [--endpoint http://localhost:8081]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")  # pyright: ignore[reportAttributeAccessIssue]

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from graph_benchmark import EMULATOR_LABEL, run_benchmark, write_evidence

REPO = Path(__file__).resolve().parents[3]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--endpoint", default="http://localhost:8081")
    ap.add_argument("--nodes", type=int, default=200)
    ap.add_argument("--iterations", type=int, default=30)
    ap.add_argument("--out", default=str(REPO / "docs" / "evidence" / "G03"))
    args = ap.parse_args()
    result = run_benchmark(
        args.endpoint, "emulator_key", nodes=args.nodes, iterations=args.iterations
    )
    jpath, mpath = write_evidence(result, args.out, EMULATOR_LABEL)
    print(f"wrote {jpath}\nwrote {mpath}\np95 ms by workload: {result.p95_by_workload()}")
    return 0 if result.all_correct else 1


if __name__ == "__main__":
    raise SystemExit(main())
