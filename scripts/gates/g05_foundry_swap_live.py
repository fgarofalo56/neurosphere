"""G05 live run (PRP-17 item 5): swap a model on a real Foundry deployment, verify, roll back.

Operator-approved only. Refuses unless NS_LIVE_APPROVED=1. The check is the first statement of
``main`` and runs before argument parsing, any Azure SDK or project import, and any network
access: this module imports only the standard library at the top level.

STATUS: the G05 live run is OPEN. The operator decided on 2026-10-20 that it does not run in
PRP-17 (see docs/evidence/G05/README.md). Nothing here has been executed against Azure.

With approval it would change a real deployment and then restore it, so it needs an
operator-chosen, non-production Commercial account and deployment:

    NS_LIVE_APPROVED=1 python scripts/gates/g05_foundry_swap_live.py \
        --subscription <guid> --resource-group <rg> --account <acct> --location <region> \
        --deployment <lowercase-name> --target-model <name> --target-version <version>

Flow: dry_run -> apply -> verify (observed state) -> rollback -> verify the restored model.
Once apply has been attempted, rollback always runs (in a ``finally``), even when apply raised
after the PUT or verify failed; it is skipped only when the connector already reported
``apply_failed_restored``. Evidence is written on every approved-path outcome.
Credentials come from ``DefaultAzureCredential`` (async; managed identity / az login); no key is
read from arguments or environment. Evidence (whitelisted fields only: ids, model names and
versions, etags, check ids and statuses) is written to docs/evidence/G05/.

Exit codes: 0 PASS, 1 FAIL (an operation failed; evidence written), 2 REFUSED (approval or
arguments; nothing was run).
"""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

EVIDENCE_DIR = Path(__file__).resolve().parents[2] / "docs" / "evidence" / "G05"


def _refuse(message: str) -> int:
    print(f"REFUSED: {message} No connection was attempted.", file=sys.stderr)
    return 2


def _parse(argv: list[str]) -> argparse.Namespace:

    p = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0] if __doc__ else None)
    for flag in (
        "subscription",
        "resource-group",
        "account",
        "location",
        "deployment",
        "target-model",
        "target-version",
    ):
        p.add_argument(f"--{flag}", required=True)
    p.add_argument("--customer", default="cust1")
    return p.parse_args(argv)


async def _exercise(
    connector: Any,
    reader: Any,
    *,
    name: str,
    customer: str,
    target_model: str,
    target_version: str,
    record: Callable[..., None],
) -> bool:
    """Run the swap cycle against ``connector``; always restore once apply was attempted."""
    import json

    from neurosphere_connector.write import ApplyResult, WriteRequest
    from neurosphere_contracts.actions.v1.action_intent import PatchOperation, ProposedDiff
    from neurosphere_contracts.actions.v1.target_ref import TargetRef

    current = await reader.get_deployment(name)
    etag = str(current.get("etag", ""))
    model = current["properties"]["model"]
    prior = {k: str(model[k]) for k in ("format", "name", "version")}
    target = TargetRef(
        canonical_id=f"commercial:{customer}:foundry:model_deployment:{name}",
        entity_type="model_deployment",
    )

    def req(model_name: str, version: str, version_etag: str) -> WriteRequest:
        diff = ProposedDiff(
            format="json_patch",
            operations=[
                PatchOperation(op="replace", path="/properties/model/name", value=model_name),
                PatchOperation(op="replace", path="/properties/model/version", value=version),
            ],
        )
        return WriteRequest(target=target, target_version=version_etag, proposed_diff=diff)

    forward = req(target_model, target_version, etag)
    record("before", model=model, etag=etag)
    ok = True
    attempted = False
    restored_by_connector = False
    applied: ApplyResult | None = None
    try:
        dry = await connector.dry_run(forward)
        record("dry_run", would_change=dry.would_change)
        checks = await connector.check_compatibility(forward)
        record("compatibility", checks=[c.model_dump() for c in checks])
        attempted = True
        result: ApplyResult = await connector.apply(forward)
        applied = result
        record("apply", version_before=result.version_before, version_after=result.version_after)
        after = await connector.verify(
            forward.model_copy(update={"target_version": result.version_after or etag})
        )
        record("verify_after_apply", matched=after.matched, mismatched=list(after.mismatched_paths))
        ok = after.matched
    except Exception as exc:
        record(
            "error",
            code=str(getattr(exc, "code", type(exc).__name__)),
            reason=str(getattr(exc, "reason", "")),
        )
        ok = False
        restored_by_connector = getattr(exc, "reason", None) == "apply_failed_restored"
    finally:
        if attempted:
            # The deployment may have been changed even when no ApplyResult exists (apply raised
            # after the PUT, or verify failed): restore from the pre-read model regardless.
            if applied is None:
                applied = ApplyResult(
                    target=target,
                    version_before=etag,
                    version_after=None,
                    applied_diff=forward.proposed_diff,
                    rollback_token=json.dumps(prior, separators=(",", ":"), sort_keys=True),
                )
            try:
                if restored_by_connector:
                    record("rollback", status="skipped_connector_restored")
                else:
                    rolled = await connector.rollback(applied)
                    record("rollback", status=rolled.status, version_after=rolled.version_after)
                latest = await reader.get_deployment(name)
                back = req(prior["name"], prior["version"], str(latest.get("etag", "")) or etag)
                restored = await connector.verify(back)
                record(
                    "verify_after_rollback",
                    matched=restored.matched,
                    mismatched=list(restored.mismatched_paths),
                )
                ok = ok and restored.matched
            except Exception as exc:
                record(
                    "rollback_error",
                    code=str(getattr(exc, "code", type(exc).__name__)),
                    reason=str(getattr(exc, "reason", "")),
                )
                ok = False
    return ok


async def _run(args: argparse.Namespace) -> int:
    import json
    from datetime import UTC, datetime

    import httpx
    from azure.identity.aio import DefaultAzureCredential
    from neurosphere_connector_foundry_actions import (
        AccountRef,
        ArmClient,
        FoundryModelSwapConnector,
        create_swap_connector,
    )
    from neurosphere_core.cloud.profile import CloudName

    ns = vars(args)
    account = AccountRef(
        cloud=CloudName.COMMERCIAL,
        subscription_id=ns["subscription"],
        resource_group=ns["resource_group"],
        account=ns["account"],
        location=ns["location"],
    )
    name = str(ns["deployment"]).lower()
    steps: list[dict[str, object]] = []
    ok = True

    def record(step: str, **fields: object) -> None:
        steps.append({"step": step, **fields})

    async with httpx.AsyncClient(timeout=30.0) as http:
        credential = DefaultAzureCredential()
        try:
            reader = ArmClient(account, credential, client=http)
            connector = await create_swap_connector(account, credential, client=http)
            if not isinstance(connector, FoundryModelSwapConnector):
                record("connector", advisory=True, reason=getattr(connector, "reason", ""))
                ok = False
            else:
                ok = await _exercise(
                    connector,
                    reader,
                    name=name,
                    customer=ns["customer"],
                    target_model=ns["target_model"],
                    target_version=ns["target_version"],
                    record=record,
                )
        except Exception as exc:
            record("error", code=type(exc).__name__, reason=str(getattr(exc, "reason", "")))
            ok = False
        finally:
            await credential.close()

    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    evidence = {
        "gate": "G05",
        "run_at": stamp,
        "result": "PASS" if ok else "FAIL",
        "account": ns["account"],
        "deployment": name,
        "api_versions": {
            "deployments": "2024-10-01",
            "models": "2024-10-01",
            "permissions": "2022-04-01",
        },
        "steps": steps,
    }
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    out = EVIDENCE_DIR / f"{stamp}-foundry-swap-live.json"
    out.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"{evidence['result']}: evidence written to {out}")
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    if os.environ.get("NS_LIVE_APPROVED") != "1":
        return _refuse(
            "g05_foundry_swap_live.py would change a real Foundry deployment and needs operator "
            "approval; set NS_LIVE_APPROVED=1."
        )
    import asyncio

    args = _parse(sys.argv[1:] if argv is None else argv)
    return asyncio.run(_run(args))


if __name__ == "__main__":
    sys.exit(main())
