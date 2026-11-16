"""G04 live check for the AWS Bedrock metadata connector (PRP-62; run by PRP-64).

Operator-approved only, AWS Commercial only. Refuses unless NS_LIVE_APPROVED=1; that check is the
first statement of ``main`` and runs before argument parsing, any import of project or AWS SDK
code, or any network call (this module imports only ``os`` and ``sys`` at top level).

What a run proves: the connector passes the contract kit and completes one bounded READ of each
source against the operator-named account and region: the Bedrock inventory (five list calls),
CloudWatch ``GetMetricData`` for up to three model ids over the last three hours, Cost Explorer
``GetCostAndUsage`` for yesterday, and the invocation-logging setting. Nothing is written to AWS
and no model is invoked.

Request budget (state this before approving): at most 5 inventory pages per list (``--max-pages``,
default 2) over 5 lists, 1 CloudWatch call, at most ``--max-pages`` Cost Explorer requests
(0.01 USD each on the primary billing view, per the AWS Cost Explorer documentation), 1 logging
call. A run is therefore well under one US cent of Cost Explorer charge at the default cap.

Credentials are never accepted as arguments or written anywhere:
- ``--auth static-key``: the JSON key document is read from the environment variable named by
  ``--key-env`` (default ``NS_AWS_BEDROCK_KEY_JSON``), installed by the operator.
- ``--auth web-identity``: an OIDC token file path is read from ``--token-file`` and exchanged
  for a short-lived role session (``--role-arn``).

Evidence is written to ``--evidence-dir`` (default docs/evidence/G04/) as
``aws-bedrock-<stamp>.json``: counts, booleans and violation codes only. No account id, ARN,
model name, amount, prompt, bucket or log-group name is recorded.

Exit codes: 2 REFUSED (approval or argument precondition; nothing was run); 3 OPEN (approved but a
prerequisite is missing or AWS refused; nothing proven); 1 the connector failed the contract;
0 only after every source really answered.
"""

from __future__ import annotations

import os
import sys

GATE = "G04"
EXIT_OK, EXIT_FAILED, EXIT_REFUSED, EXIT_OPEN = 0, 1, 2, 3
DEFAULT_KEY_ENV = "NS_AWS_BEDROCK_KEY_JSON"
MAX_MODELS = 3


class RefusedError(Exception):
    """A precondition failed before anything ran (exit 2)."""


def _refuse_message() -> str:
    return (
        "REFUSED: live_check.py reads a live AWS account and needs operator approval; "
        "set NS_LIVE_APPROVED=1. No connection was attempted."
    )


def build_parser():  # type: ignore[no-untyped-def]
    import argparse

    ap = argparse.ArgumentParser(description="AWS Bedrock metadata live check (operator-approved).")
    ap.add_argument("--region", required=True, help="one commercial AWS region, e.g. us-east-1")
    ap.add_argument("--auth", choices=("static-key", "web-identity"), required=True)
    ap.add_argument("--key-env", default=DEFAULT_KEY_ENV, help="env var holding the key JSON")
    ap.add_argument("--role-arn", help="IAM role ARN for --auth web-identity")
    ap.add_argument("--token-file", help="OIDC token file for --auth web-identity")
    ap.add_argument("--max-pages", type=int, default=2, help="page budget per list (and CE calls)")
    ap.add_argument("--budget-cap-usd", type=float, default=0.0, help="required, > 0")
    ap.add_argument("--evidence-dir", default="docs/evidence/G04")
    return ap


def evidence_record(
    *,
    region: str,
    auth: str,
    violations: list[str],
    inventory: dict[str, object],
    usage_points: int,
    usage_reported: int,
    cost_days: int,
    cost_reported: int,
    logging_configured: bool,
    max_pages: int,
    observed_at: str,
) -> dict[str, object]:
    """The whitelisted evidence document. Nothing outside these keys is ever written."""
    return {
        "gate": GATE,
        "connector": "aws-bedrock-metadata",
        "observed_at": observed_at,
        "region": region,
        "auth": auth,
        "contract_violations": sorted(violations),
        "inventory": inventory,
        "usage": {"points": usage_points, "reported": usage_reported},
        "cost": {"days": cost_days, "reported": cost_reported},
        "invocation_logging_configured": logging_configured,
        "page_budget": max_pages,
        "note": "counts only; no ids, names, amounts or content were recorded",
    }


async def run_checks(connector, *, region: str, auth: str, max_pages: int):  # type: ignore[no-untyped-def]
    """Contract kit plus one bounded read per source. Returns ``(evidence, all_answered)``."""
    from datetime import UTC, datetime, timedelta

    from neurosphere_connector.contract_kit import check_connector_contract
    from neurosphere_connector_aws_bedrock.models import CostWindow, UsageWindow

    now = datetime.now(UTC)
    violations = [v.code for v in await check_connector_contract(connector)]
    inv = await connector.inventory()
    lists = {
        "foundation_models": inv.foundation_models,
        "custom_models": inv.custom_models,
        "provisioned_throughput": inv.provisioned_throughput,
        "guardrails": inv.guardrails,
        "agents": inv.agents,
    }
    inventory: dict[str, object] = {
        name: (None if items is None else len(items)) for name, items in lists.items()
    }
    inventory["truncated"] = sorted(inv.truncated)
    inventory["failed_sources"] = sorted(inv.failed_sources)

    hour = now.replace(minute=0, second=0, microsecond=0)
    models = [m.id for m in (inv.foundation_models or [])][:MAX_MODELS]
    usage_points = usage_reported = 0
    answered = not inv.failed_sources
    if models:
        usage = await connector.usage(
            UsageWindow(start=hour - timedelta(hours=3), end=hour), models
        )
        usage_points = len(usage.points)
        usage_reported = sum(p.value is not None for p in usage.points)
    today = now.date()
    cost = await connector.cost(CostWindow(start=today - timedelta(days=1), end=today))
    state = await connector.logging_state()
    record = evidence_record(
        region=region,
        auth=auth,
        violations=violations,
        inventory=inventory,
        usage_points=usage_points,
        usage_reported=usage_reported,
        cost_days=len(cost.points),
        cost_reported=sum(p.amount is not None for p in cost.points),
        logging_configured=state.configured,
        max_pages=max_pages,
        observed_at=now.isoformat(),
    )
    return record, answered and not violations


def _build_connector(args):  # type: ignore[no-untyped-def]
    """Real connector from the operator-installed credential path (lazy imports)."""
    import asyncio
    from pathlib import Path

    from neurosphere_connector import CredentialBroker, SecretValue, StaticCredentialResolver
    from neurosphere_connector_aws_bedrock.aws_auth import (
        DEFAULT_CREDENTIAL_NAME,
        StaticKeyProvider,
        WebIdentityProvider,
    )
    from neurosphere_connector_aws_bedrock.boto3_reader import Boto3BedrockReader
    from neurosphere_connector_aws_bedrock.connector import AwsBedrockConnector
    from neurosphere_contracts.connectors.v1.connector_manifest import CredentialRef
    from neurosphere_core.cloud.profile import CloudName

    refs = ()
    if args.auth == "static-key":
        raw = os.environ.get(args.key_env)
        if not raw:
            raise RefusedError(f"environment variable {args.key_env} is not set")
        ref = CredentialRef(
            name=DEFAULT_CREDENTIAL_NAME,
            vault_ref="https://live-check.vault.azure.net/secrets/aws-bedrock-live-check",
        )
        refs = (ref,)
        resolver = StaticCredentialResolver({ref.vault_ref: raw})
        provider = StaticKeyProvider(CredentialBroker(resolver, refs))
        auth_mode = "vault_reference"
    else:
        if not args.role_arn or not args.token_file:
            raise RefusedError("--auth web-identity needs --role-arn and --token-file")
        token_path = args.token_file

        async def token_source() -> SecretValue:
            text = await asyncio.to_thread(Path(token_path).read_text, encoding="utf-8")
            return SecretValue(text.strip())

        provider = WebIdentityProvider(
            role_arn=args.role_arn,
            session_name="neurosphere-live-check",
            token_source=token_source,
            region=args.region,
        )
        auth_mode = "workload_identity_federation"
    reader = Boto3BedrockReader(provider=provider, region=args.region, max_pages=args.max_pages)
    return AwsBedrockConnector(
        reader=reader,
        cloud=CloudName.COMMERCIAL,
        region=args.region,
        max_items=50,
        auth_mode=auth_mode,
        credential_refs=refs,
    )


def main(argv: list[str] | None = None) -> int:
    if os.environ.get("NS_LIVE_APPROVED") != "1":
        print(_refuse_message(), file=sys.stderr)
        return EXIT_REFUSED
    import asyncio
    import json
    from datetime import UTC, datetime
    from pathlib import Path

    args = build_parser().parse_args(argv)
    try:
        if args.budget_cap_usd <= 0:
            raise RefusedError("--budget-cap-usd must be greater than 0 (record the cap)")
        if args.max_pages < 1 or args.max_pages > 5:
            raise RefusedError("--max-pages must be between 1 and 5")
        connector = _build_connector(args)
    except RefusedError as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return EXIT_REFUSED
    except Exception as exc:  # a typed refusal such as a Government cloud or bad region
        print(f"REFUSED: {type(exc).__name__}", file=sys.stderr)
        return EXIT_REFUSED

    from neurosphere_core.errors import NeuroSphereError

    async def go():  # type: ignore[no-untyped-def]
        try:
            return await run_checks(
                connector, region=args.region, auth=args.auth, max_pages=args.max_pages
            )
        finally:
            await connector.close()

    try:
        record, ok = asyncio.run(go())
    except NeuroSphereError as exc:
        print(f"OPEN: G04 AWS Bedrock live check did not complete: {exc.code}.")
        return EXIT_OPEN
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    out = Path(args.evidence_dir)
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"aws-bedrock-{stamp}.json"
    path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"evidence written: {path}")
    if not ok:
        print("FAILED: contract violations or an inventory source failed; see the evidence file.")
        return EXIT_FAILED
    print("G04 AWS Bedrock live check: every source answered. G04 as a whole stays OPEN.")
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
