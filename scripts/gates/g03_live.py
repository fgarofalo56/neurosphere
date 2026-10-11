"""G03 live run: the graph partition/traversal benchmark against a real Cosmos DB account.

Operator-approved only. Refuses unless NS_LIVE_APPROVED=1 (checked first, before any
config, import of azure packages or network access).

Environment:
  NS_LIVE_APPROVED=1            required approval gate
  NS_G03_COSMOS_ENDPOINT        required, e.g. https://<account>.documents.azure.com:443/
  NS_G03_ACCOUNT_SKU            optional, account SKU/capacity mode (e.g. serverless)
  NS_G03_ACCOUNT_REGION         optional, account region (e.g. eastus2)
  NS_G03_OPERATOR               optional, operator name (or --operator)

Auth is Entra only (DefaultAzureCredential / managed identity). No key or connection
string is accepted anywhere. Writes docs/evidence/G03/live-<date>.{md,json}.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
LIVE_LABEL = "live, Commercial Cosmos DB account (operator-approved)"
ENDPOINT_ENV = "NS_G03_COSMOS_ENDPOINT"


def main(argv: list[str] | None = None) -> int:
    if os.environ.get("NS_LIVE_APPROVED") != "1":
        print(
            "REFUSED: g03_live.py needs operator approval; set NS_LIVE_APPROVED=1. "
            "No connection was attempted.",
            file=sys.stderr,
        )
        return 2

    args = build_parser().parse_args(argv)
    endpoint = os.environ.get(ENDPOINT_ENV, "").strip()
    if not endpoint:
        print(f"ERROR: set {ENDPOINT_ENV} to the Cosmos account endpoint.", file=sys.stderr)
        return 2
    if not endpoint.startswith("https://"):
        print(f"ERROR: {ENDPOINT_ENV} must be an https:// endpoint.", file=sys.stderr)
        return 2

    sys.path.insert(0, str(REPO / "tests" / "load"))
    import importlib

    bench = importlib.import_module("graph_benchmark")
    run_benchmark, write_evidence = bench.run_benchmark, bench.write_evidence

    operator = args.operator or os.environ.get("NS_G03_OPERATOR") or "unspecified"
    sku = os.environ.get("NS_G03_ACCOUNT_SKU") or "unspecified"
    region = args.region_label or os.environ.get("NS_G03_ACCOUNT_REGION") or "unspecified"

    result = run_benchmark(
        endpoint,
        credential_mode="default_azure_credential",
        iterations=args.iterations,
    )
    result.environment["live_account"] = {
        "operator": operator,
        "sku": sku,
        "region": region,
        "source": "operator-supplied via environment/flags (not read from the management API)",
    }
    jpath, mpath = write_evidence(result, args.out_dir, LIVE_LABEL, slug="live")
    print(f"wrote {jpath}\nwrote {mpath}\np95 ms by workload: {result.p95_by_workload()}")
    return 0 if result.all_correct else 1


def build_parser():
    import argparse

    ap = argparse.ArgumentParser(description="G03 live Cosmos benchmark (Entra auth only).")
    ap.add_argument("--out-dir", default=str(REPO / "docs" / "evidence" / "G03"))
    ap.add_argument("--iterations", type=int, default=30)
    ap.add_argument("--operator", default=None, help="operator name for the evidence header")
    ap.add_argument("--region-label", default=None, help="account region for the header")
    return ap


if __name__ == "__main__":
    raise SystemExit(main())
