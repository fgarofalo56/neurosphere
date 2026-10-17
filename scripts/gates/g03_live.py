"""G03 live run: the graph partition/traversal benchmark against a real Cosmos DB account.

Operator-approved only. Refuses unless NS_LIVE_APPROVED=1 (checked first, before any
config, import of azure packages or network access).

Environment:
  NS_LIVE_APPROVED=1            required approval gate
  NS_G03_COSMOS_ENDPOINT        required, e.g. https://<account>.documents.azure.com:443/
  NS_G03_RESOURCE_GROUP         required, resource group of the Cosmos account
  NS_G03_SUBSCRIPTION           required, subscription GUID; must equal `az account show` id
  NS_G03_ACCOUNT_SKU           optional, account SKU/capacity mode (e.g. serverless)
  NS_G03_ACCOUNT_REGION         optional, account region (e.g. eastus2)
  NS_G03_OPERATOR               optional, operator name (or --operator)

Auth is Entra only (DefaultAzureCredential / managed identity). No key or connection
string is accepted anywhere. The Cosmos account name is the endpoint host's first label.
Databases/containers are created and deleted through the control plane with the Azure CLI
(`az login` first) because Entra data-plane tokens cannot (403, substatus 5300); the
benchmark itself runs over the data plane with Entra. Needs a control-plane role that can
create/delete SQL databases and containers (e.g. Cosmos DB Operator) plus a data-plane role
(Cosmos DB Built-in Data Contributor). Writes docs/evidence/G03/live-<date>.{md,json}.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

REPO = Path(__file__).resolve().parents[2]
LIVE_LABEL = "live, Commercial Cosmos DB account (operator-approved)"
ENDPOINT_ENV = "NS_G03_COSMOS_ENDPOINT"
RESOURCE_GROUP_ENV = "NS_G03_RESOURCE_GROUP"
SUBSCRIPTION_ENV = "NS_G03_SUBSCRIPTION"


def main(argv: list[str] | None = None, runner: Any = None) -> int:
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

    host = (urlparse(endpoint).hostname or "").lower()
    if host.endswith(".azure.us") or "usgovcloudapi" in host or "documents.azure.us" in host:
        print(
            f"ERROR: {ENDPOINT_ENV} is a Government endpoint; this script's evidence is labelled "
            "Commercial and must not be run against Azure Government. No connection was attempted.",
            file=sys.stderr,
        )
        return 2

    resource_group = os.environ.get(RESOURCE_GROUP_ENV, "").strip()
    subscription = os.environ.get(SUBSCRIPTION_ENV, "").strip()
    account = host.split(".", 1)[0]

    sys.path.insert(0, str(REPO / "tests" / "load"))
    import importlib

    prov = importlib.import_module("graph_benchmark.provision")
    if not resource_group or not subscription:
        print(
            f"ERROR: set {RESOURCE_GROUP_ENV} and {SUBSCRIPTION_ENV}; databases are created "
            "through the control plane. Nothing was created.",
            file=sys.stderr,
        )
        return 2
    if not prov.valid_account_name(account):
        print(f"ERROR: account name {account!r} (from the endpoint) is invalid.", file=sys.stderr)
        return 2
    if not prov.valid_resource_group(resource_group):
        print(f"ERROR: {RESOURCE_GROUP_ENV} is malformed. Nothing was created.", file=sys.stderr)
        return 2
    if not prov.valid_subscription(subscription):
        print(f"ERROR: {SUBSCRIPTION_ENV} must be a GUID. Nothing was created.", file=sys.stderr)
        return 2
    if runner is None:
        az_path = prov.resolve_az()
        if not az_path:
            print("REFUSED: the Azure CLI (az) was not found on PATH.", file=sys.stderr)
            return 2
        runner = prov.SubprocessAzRunner(az_path)
    try:
        active = prov.current_subscription(runner)
    except prov.ProvisioningError as exc:
        print(f"REFUSED: {exc}. Nothing was created.", file=sys.stderr)
        return 2
    if active.lower() != subscription.lower():
        print(
            f"REFUSED: the active az subscription does not match {SUBSCRIPTION_ENV}. "
            "Run `az account set` or fix the variable. Nothing was created.",
            file=sys.stderr,
        )
        return 2
    provisioner = prov.AzCliProvisioner(account, resource_group, subscription, runner)

    bench = importlib.import_module("graph_benchmark")
    run_benchmark, write_evidence = bench.run_benchmark, bench.write_evidence

    operator = args.operator or os.environ.get("NS_G03_OPERATOR") or "unspecified"
    sku = os.environ.get("NS_G03_ACCOUNT_SKU") or "unspecified"
    region = args.region_label or os.environ.get("NS_G03_ACCOUNT_REGION") or "unspecified"

    result = run_benchmark(
        endpoint,
        credential_mode="default_azure_credential",
        iterations=args.iterations,
        provisioner=provisioner,
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
