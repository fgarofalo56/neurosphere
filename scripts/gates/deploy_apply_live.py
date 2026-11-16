"""PRP-55 live runner, handed to PRP-64: apply an approved plan into a throwaway resource group.

Operator-approved only. Refuses unless NS_LIVE_APPROVED=1. The check is the first statement of
``main`` and runs before argument parsing, any Azure SDK or project import and any network
access: this module imports only the standard library at the top level.

STATUS: OPEN. Not run in PRP-55 (no live call without operator approval in the session). PRP-64
owns the live run, its spend row and its evidence.

What it does with approval (BILLABLE: it creates real Azure resources):

1. Approves a minimal deployment plan (by default one ``storage`` account; ``--services`` adds
   ``event_hubs`` / ``monitoring``, the decision-2 allowlist) through the same
   ``PlanApprovalStore`` the API uses, targeted at an EXISTING, operator-created, throwaway
   resource group (decision 3: the runner never creates or deletes a resource group).
2. Drives the worker's ``DeployConnector`` (real ``HttpArmProvisioner`` over the bearer transport,
   ``DefaultAzureCredential``; Commercial or Government management host from ``NS_CLOUD``) through
   ``dry_run`` -> ``apply`` -> ``verify`` (read-back) with an in-memory register.
3. Writes evidence (whitelisted fields only: tokenised subscription, resource types and names,
   created flags, verify result; never a subscription id, token or key; the repo is public) to
   ``docs/evidence/PRP-55/``.

Teardown is NOT automatic: remove what the evidence lists with the guarded uninstall tool
(``infra/scripts/uninstall.py`` under ``NS_LIVE_APPROVED=1``) or delete the throwaway resource
group. Operator run, for PRP-64:

    az group create -n <throwaway-rg> -l eastus2 --tags project=neurosphere owner=<you>
    NS_LIVE_APPROVED=1 python scripts/gates/deploy_apply_live.py \
        --subscription <guid> --resource-group <throwaway-rg> --region eastus2 \
        --deployment-id ns-live-<yyyymmdd>

Exit codes: 0 PASS, 1 FAIL (an operation failed; evidence written), 2 REFUSED (approval or
arguments; nothing was run).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")  # pyright: ignore[reportAttributeAccessIssue]

EVIDENCE_DIR = Path(__file__).resolve().parents[2] / "docs" / "evidence" / "PRP-55"
LIVE_APPROVAL_ENV = "NS_LIVE_APPROVED"
EXIT_PASS, EXIT_FAIL, EXIT_REFUSED = 0, 1, 2
ALLOWED_SERVICES = ("storage", "event_hubs", "monitoring")
_GUID = re.compile(r"^[0-9a-fA-F]{8}-([0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}$")
_DEPLOYMENT = re.compile(r"^[a-z0-9][a-z0-9-]{2,62}$")
_RG = re.compile(r"^[\w.()-]{1,90}$")
_REGION = re.compile(r"^[a-z][a-z0-9]{2,39}$")


def _refuse(message: str) -> int:
    print(f"REFUSED: {message} No connection was attempted.", file=sys.stderr)
    return EXIT_REFUSED


def _parse(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="PRP-55 live deploy apply (throwaway resource group)")
    p.add_argument("--subscription", required=True)
    p.add_argument("--resource-group", required=True)
    p.add_argument("--region", required=True)
    p.add_argument("--deployment-id", required=True)
    p.add_argument("--services", nargs="+", default=["storage"], choices=ALLOWED_SERVICES)
    return p.parse_args(argv)


def _valid(args: argparse.Namespace) -> str | None:
    if not _GUID.fullmatch(args.subscription):
        return "--subscription must be a GUID."
    if not _RG.fullmatch(args.resource_group):
        return "--resource-group is not a valid resource group name."
    if not _REGION.fullmatch(args.region):
        return "--region must be a lowercase ARM region name."
    if not _DEPLOYMENT.fullmatch(args.deployment_id):
        return "--deployment-id must match ^[a-z0-9][a-z0-9-]{2,62}$."
    return None


def tokenise(subscription_id: str) -> str:
    """Stable, non-reversible token for a subscription id (evidence is public)."""
    return "sub-" + hashlib.sha256(subscription_id.lower().encode()).hexdigest()[:12]


def _scrub(text: str, subscription_id: str) -> str:
    return re.sub(re.escape(subscription_id), tokenise(subscription_id), text, flags=re.IGNORECASE)


async def _run(args: argparse.Namespace) -> int:  # pragma: no cover - live only
    import httpx
    from azure.identity.aio import DefaultAzureCredential
    from neurosphere_api.deploy.apply import PlanApprovalStore
    from neurosphere_api.deploy.apply.models import ApplyTarget
    from neurosphere_api.deploy.plan import DeploymentPlan, PlanCheck, PlanCost, PlanItem
    from neurosphere_connector.write import WriteRequest
    from neurosphere_contracts.scope.v1.identity_scope import IdentityScope as ContractScope
    from neurosphere_core.capabilities import DeploymentProfile
    from neurosphere_core.cloud import load_settings
    from neurosphere_core.deploy.register import CustomerScopedRegister, InMemoryRegisterStore
    from neurosphere_core.scope import IdentityScope
    from neurosphere_workers.actions.deploy import DeployConnector, apply_diff, plan_target
    from neurosphere_workers.actions.deploy_arm import HttpArmProvisioner
    from neurosphere_workers.actions.deploy_http import BearerDeployHttp, deploy_scopes

    settings = load_settings()
    profile = settings.cloud_profile
    cloud = profile.cloud.value
    now = datetime.now(UTC)
    customer = "live-operator"
    scope = IdentityScope._from_verified_contract(  # pyright: ignore[reportPrivateUsage]
        ContractScope.model_validate(
            {
                "schema_version": "1.0.0",
                "cloud": cloud,
                "customer_id": customer,
                "principal": {
                    "principal_id": f"{cloud}:{customer}:entra:person:p-live",
                    "principal_pseudonym": "p-live",
                    "principal_kind": "user",
                },
                "roles": [],
                "allowed_domains": [],
                "allowed_resources": [],
                "policy_version": "live",
                "derived_at": now.isoformat(),
                "expires_at": (now + timedelta(minutes=15)).isoformat(),
                "scope_hash": "sha256:" + "0" * 64,
            }
        )
    )
    plan = DeploymentPlan(
        plan_id=f"plan-live-{now:%Y%m%d%H%M%S}",
        deployment_id=args.deployment_id,
        profile=DeploymentProfile(
            cloud=cloud,  # type: ignore[arg-type]
            regions=(args.region,),
            hosting="aks",
            analytics="fabric",
        ),
        items=[
            PlanItem(
                service=service,
                status="create",
                cost_implication=PlanCost(basis="unknown"),
                checks=[PlanCheck(name="permission", outcome="pass", reason="operator live run")],
            )
            for service in args.services
        ],
        created_at=now,
    )
    target = ApplyTarget(
        subscription_id=args.subscription, resource_group=args.resource_group, region=args.region
    )
    evidence: dict[str, Any] = {
        "gate": "PRP-55 live deploy apply",
        "cloud": cloud,
        "subscription": tokenise(args.subscription),
        "region": args.region,
        "deployment_id": args.deployment_id,
        "started_at": now.isoformat(),
    }
    code = EXIT_FAIL
    async with DefaultAzureCredential() as credential, httpx.AsyncClient(timeout=30.0) as client:
        approvals = PlanApprovalStore()
        record = await approvals.approve(scope, plan, target)
        action_plan = record.action_plan()
        register = InMemoryRegisterStore()
        http = BearerDeployHttp(client, lambda: credential, deploy_scopes(profile))
        connector = DeployConnector(
            cloud=profile.cloud,
            customer_id=customer,
            approvals=approvals,
            register=CustomerScopedRegister(register, customer),
            arm=HttpArmProvisioner(http, profile),
        )
        request = WriteRequest(
            target=plan_target(cloud, customer, action_plan.plan_id),
            target_version=action_plan.plan_hash,
            proposed_diff=apply_diff(action_plan),
        )
        try:
            await connector.dry_run(request)
            await connector.apply(request)
            verified = await connector.verify(request)
            rows = await register.list_rows(args.deployment_id)
            evidence["resources"] = [
                {
                    "service": r.service,
                    "ownership": r.ownership.value,
                    "name": r.resource_id.rsplit("/", 1)[-1],
                }
                for r in rows
            ]
            evidence["verify_matched"] = verified.matched
            code = EXIT_PASS if verified.matched else EXIT_FAIL
        except Exception as exc:  # evidence by type and reason only, never a value
            evidence["error"] = {"type": type(exc).__name__, "reason": getattr(exc, "reason", None)}
    evidence["result"] = "PASS" if code == EXIT_PASS else "FAIL"
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    out = EVIDENCE_DIR / f"{now:%Y-%m-%d}-deploy-apply-live.json"
    out.write_text(_scrub(json.dumps(evidence, indent=2), args.subscription), encoding="utf-8")
    print(f"{evidence['result']}: evidence written to {out.relative_to(EVIDENCE_DIR.parents[2])}")
    return code


def main(argv: list[str] | None = None) -> int:
    if os.environ.get(LIVE_APPROVAL_ENV) != "1":
        return _refuse(
            "deploy_apply_live.py creates billable Azure resources and needs operator approval; "
            "set NS_LIVE_APPROVED=1 (PRP-64 runs it)."
        )
    try:
        args = _parse(sys.argv[1:] if argv is None else argv)
    except SystemExit:
        return EXIT_REFUSED
    problem = _valid(args)
    if problem is not None:
        return _refuse(problem)
    import asyncio

    return asyncio.run(_run(args))


if __name__ == "__main__":
    sys.exit(main())
