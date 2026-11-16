"""G04 live run: Azure Monitor, Foundry discovery and billing export read paths (#220).

Operator-approved only, Azure Commercial only. Refuses unless NS_LIVE_APPROVED=1; that check is
the first statement of ``main`` and runs before argument parsing, any import of project or Azure
code, or any network call (this module imports only ``os`` and ``sys`` at top level).

What a run proves: with the operator's managed identity or developer sign-in, each approved
connector (a) passes the connector contract kit (``check_connector_contract``) and (b) completes
one bounded READ against the operator-named target: a Log Analytics query slice, a Foundry project
agent and deployment listing, a Cost Management export read. Nothing is written to Azure. A run
does NOT prove ingest end to end (producer, secret, stored connector config); that is the hosted
ingest smoke of PRP-64.

Every approved step names its connector: ``--approve-step azure-monitor`` and so on. Without a
step the connector is not run. A budget cap in USD is required (spend is pre-authorized for
NeuroSphere, but each run records its cap).

Evidence is written to ``--evidence-dir`` (default docs/evidence/G04/), scrubbed of subscription
ids, tenant ids, GUIDs, resource names and hosts: counts and violation codes only. This script
makes no evidence by itself; it is evidence only when an operator runs it.

Exit codes: 2 REFUSED (approval, cloud, budget or argument precondition; nothing was run);
3 OPEN (approved but a prerequisite is missing or the target refused; nothing proven);
1 a connector failed its contract or read; 0 only after every approved connector really ran.
"""

from __future__ import annotations

import os
import sys

GATE = "G04"
CONNECTORS = ("azure-monitor", "foundry-discovery", "billing-export")
MAX_BUDGET_USD = 25.0
EXIT_OK, EXIT_FAILED, EXIT_REFUSED, EXIT_OPEN = 0, 1, 2, 3


class RefusedError(Exception):
    """A precondition failed before anything ran (exit 2)."""


class OpenGateError(Exception):
    """Approved, but a prerequisite is missing or the target refused (exit 3)."""


def _refuse_message() -> str:
    return (
        "REFUSED: g04_connectors_live.py reads live Azure targets and needs operator approval; "
        "set NS_LIVE_APPROVED=1. No connection was attempted."
    )


def build_parser():  # type: ignore[no-untyped-def]
    import argparse

    ap = argparse.ArgumentParser(description="G04 connectors live gate (operator-approved).")
    ap.add_argument("--cloud", default="commercial", choices=("commercial", "government"))
    ap.add_argument("--budget-cap-usd", type=float, default=0.0, help="required, > 0")
    ap.add_argument(
        "--approve-step",
        action="append",
        default=[],
        choices=CONNECTORS,
        help="connector to run; repeat per connector",
    )
    ap.add_argument("--operator", default="", help="name or handle recorded with the run")
    ap.add_argument("--monitor-workspace-id", default="", help="Log Analytics workspace GUID")
    ap.add_argument("--foundry-project-endpoint", default="", help="https Foundry project endpoint")
    ap.add_argument("--billing-account-url", default="", help="https blob endpoint of the export")
    ap.add_argument("--billing-container", default="", help="export container name")
    ap.add_argument("--billing-manifest-blob", default="", help="manifest blob of the export run")
    ap.add_argument("--billing-basis", default="actual", choices=("actual", "amortized"))
    ap.add_argument("--evidence-dir", default="")
    return ap


_TARGET_ARGS = {
    "azure-monitor": ("monitor_workspace_id",),
    "foundry-discovery": ("foundry_project_endpoint",),
    "billing-export": ("billing_account_url", "billing_container", "billing_manifest_blob"),
}


def validate(args) -> None:  # type: ignore[no-untyped-def]
    if args.cloud != "commercial":
        raise RefusedError(
            "G04 runs on Azure Commercial only: the billing export and Foundry discovery gates "
            "of the connectors refuse Government here. No changes made."
        )
    if not 0 < args.budget_cap_usd <= MAX_BUDGET_USD:
        raise RefusedError(
            f"--budget-cap-usd is required and must be > 0 and <= {MAX_BUDGET_USD:g}."
        )
    if not args.approve_step:
        raise RefusedError("no --approve-step given; name each connector to run.")
    import re

    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{1,127}", args.operator or ""):
        raise RefusedError("--operator is required (a name or handle, not an email address).")
    for step in args.approve_step:
        missing = [a for a in _TARGET_ARGS[step] if not str(getattr(args, a) or "").strip()]
        if missing:
            flags = ", ".join("--" + m.replace("_", "-") for m in missing)
            raise RefusedError(f"--approve-step {step} needs {flags}.")
    for attr in ("foundry_project_endpoint", "billing_account_url"):
        value = str(getattr(args, attr) or "")
        if value and not value.startswith("https://"):
            raise RefusedError(f"--{attr.replace('_', '-')} must be an https URL.")


# --------------------------------------------------------------------------- scrubbing

_GUID = r"[0-9a-fA-F]{8}-(?:[0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}"


def scrub(value, literals):  # type: ignore[no-untyped-def]
    """Recursively redact GUIDs, URLs, ARM ids and the operator-named target values."""
    import re

    if isinstance(value, dict):
        return {str(k): scrub(v, literals) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [scrub(v, literals) for v in value]
    if not isinstance(value, str):
        return value
    text = value
    for literal in sorted((x for x in literals if x), key=len, reverse=True):
        text = text.replace(literal, "<redacted>")
    text = re.sub(r"https?://[^\s\"']+", "<url:redacted>", text)
    text = re.sub(r"/subscriptions/[^\s\"']+", "<arm-id:redacted>", text)
    return re.sub(_GUID, "<guid:redacted>", text)


# --------------------------------------------------------------------------- runners


async def _run_azure_monitor(args):  # type: ignore[no-untyped-def]
    from neurosphere_connector.contract_kit import check_connector_contract
    from neurosphere_connector_azure_monitor.auth import ManagedIdentityTokenProvider
    from neurosphere_connector_azure_monitor.connector import AzureMonitorConnector
    from neurosphere_connector_azure_monitor.queries import MonitorSource, SourceKind
    from neurosphere_core.cloud.profile import CloudName

    tokens = ManagedIdentityTokenProvider(CloudName.COMMERCIAL)
    connector = AzureMonitorConnector(token_provider=tokens, cloud=CloudName.COMMERCIAL)
    try:
        violations = await check_connector_contract(connector)
        result = await connector.poll(
            [MonitorSource(SourceKind.LOG_ANALYTICS, args.monitor_workspace_id)]
        )
    finally:
        await connector.close()
        await tokens.aclose()
    return {
        "connector": "azure-monitor",
        "contract_violations": [v.code for v in violations],
        "read": {
            "records": len(result.records),
            "partial": result.partial,
            "requests_made": result.requests_made,
            "failed_sources": len(result.failed_sources),
        },
        "ok": not violations and not result.failed_sources,
    }


async def _run_foundry_discovery(args):  # type: ignore[no-untyped-def]
    from neurosphere_connector.contract_kit import check_connector_contract
    from neurosphere_connector_foundry.connector import FoundryDiscoveryConnector
    from neurosphere_connector_foundry.reader import RestProjectReader, default_token_provider
    from neurosphere_core.cloud.profile import CloudName

    cloud = CloudName.COMMERCIAL
    reader = RestProjectReader(
        endpoint=args.foundry_project_endpoint,
        token_provider=default_token_provider(cloud),
        cloud=cloud,
    )
    connector = FoundryDiscoveryConnector(
        reader=reader, cloud=cloud, project_endpoint=args.foundry_project_endpoint
    )
    try:
        violations = await check_connector_contract(connector)
        result = await connector.discover()
    finally:
        await connector.close()
    return {
        "connector": "foundry-discovery",
        "contract_violations": [v.code for v in violations],
        "read": {
            "agents": None if result.agents is None else len(result.agents),
            "deployments": None if result.deployments is None else len(result.deployments),
            "failed_sources": len(result.failed_sources),
        },
        "ok": not violations and not result.failed_sources,
    }


async def _run_billing_export(args):  # type: ignore[no-untyped-def]
    from azure.identity.aio import DefaultAzureCredential
    from neurosphere_connector.contract_kit import check_connector_contract
    from neurosphere_connector_azure_billing.blob_source import AzureBlobExportSource
    from neurosphere_connector_azure_billing.connector import AzureBillingConnector

    async with DefaultAzureCredential() as credential:
        source = AzureBlobExportSource(
            account_url=args.billing_account_url,
            container=args.billing_container,
            manifest_blob=args.billing_manifest_blob,
            credential=credential,
        )
        connector = AzureBillingConnector(source=source, basis=args.billing_basis)
        try:
            violations = await check_connector_contract(connector)
            result = await connector.read()
        finally:
            await source.close()
            await connector.close()
    return {
        "connector": "billing-export",
        "contract_violations": [v.code for v in violations],
        "read": {
            "aggregates": len(result.aggregates),
            "rows_dropped_no_date": result.rows_dropped_no_date,
            "complete": bool(result.export.complete),
        },
        "ok": not violations,
    }


RUNNERS = {
    "azure-monitor": _run_azure_monitor,
    "foundry-discovery": _run_foundry_discovery,
    "billing-export": _run_billing_export,
}


async def _run_all(args, runners):  # type: ignore[no-untyped-def]
    rows = []
    for step in CONNECTORS:
        if step not in args.approve_step:
            continue
        try:
            rows.append(await runners[step](args))
        except OpenGateError:
            raise
        except ImportError as exc:
            raise OpenGateError(
                f"{step}: a dependency is not installed ({type(exc).__name__})"
            ) from exc
        except Exception as exc:  # live failure: never echo the message, it may name a resource
            raise OpenGateError(
                f"{step}: the live read did not complete ({type(exc).__name__})"
            ) from exc
    return rows


def write_evidence(args, rows, evidence_dir):  # type: ignore[no-untyped-def]
    import json
    from datetime import UTC, datetime
    from pathlib import Path

    now = datetime.now(UTC)
    literals = [
        args.monitor_workspace_id,
        args.foundry_project_endpoint,
        args.billing_account_url,
        args.billing_container,
        args.billing_manifest_blob,
    ]
    document = scrub(
        {
            "gate": GATE,
            "utc": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "cloud": args.cloud,
            "operator": args.operator,
            "budget_cap_usd": args.budget_cap_usd,
            "approved_steps": list(args.approve_step),
            "results": rows,
            "result": "PASS" if all(r["ok"] for r in rows) else "FAIL",
            "note": "counts and codes only; targets are scrubbed",
        },
        literals,
    )
    out = Path(evidence_dir)
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"connectors-{now.strftime('%Y%m%dT%H%M%SZ')}.json"
    path.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def main(argv=None, runners=None) -> int:  # type: ignore[no-untyped-def]
    if os.environ.get("NS_LIVE_APPROVED") != "1":
        print(_refuse_message(), file=sys.stderr)
        return EXIT_REFUSED
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")  # pyright: ignore[reportAttributeAccessIssue]
    args = build_parser().parse_args(argv)
    try:
        validate(args)
    except RefusedError as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return EXIT_REFUSED
    import asyncio
    from pathlib import Path

    evidence_dir = args.evidence_dir or str(
        Path(__file__).resolve().parents[2] / "docs" / "evidence" / GATE
    )
    try:
        rows = asyncio.run(_run_all(args, runners or RUNNERS))
    except OpenGateError as exc:
        print(f"OPEN: G04 did not run to completion: {exc}.")
        return EXIT_OPEN
    path = write_evidence(args, rows, evidence_dir)
    failed = [r["connector"] for r in rows if not r["ok"]]
    print(f"G04 evidence written to {path.name} ({len(rows)} connector(s)).")
    if failed:
        print(f"FAIL: {', '.join(failed)}", file=sys.stderr)
        return EXIT_FAILED
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
