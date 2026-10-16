"""Guarded NeuroSphere uninstall (PRP-08 item 5).

Reads the ownership register (a JSON export, or the Cosmos store) and removes ONLY resources the
register records as created by NeuroSphere with no foreign dependents. Azure tags are never
consulted. A resource absent from the register is never touched.

    python infra/scripts/uninstall.py --export register.json --dry-run [--report out.json]
    python infra/scripts/uninstall.py --cosmos-database D --cosmos-container C \
        --deployment-id ID --dry-run
    NS_LIVE_APPROVED=1 python infra/scripts/uninstall.py --export register.json --confirm ID

Real removal needs NS_LIVE_APPROVED=1 and --confirm equal to the register's deployment id. It is
live-gated: it has not been exercised against Azure (gate reported OPEN).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Final

from neurosphere_core.deploy.register import (
    RegisterExport,
    RemovalPlan,
    ResourceRow,
    plan_removal,
    remove,
)
from neurosphere_core.errors import NeuroSphereError

LIVE_APPROVAL_ENV: Final = "NS_LIVE_APPROVED"
EXIT_REFUSED: Final = 3

# ARM api-version per resource type; a type not listed is refused, never guessed.
_API_VERSIONS: Final = {
    "microsoft.resources/resourcegroups": "2022-09-01",
    "microsoft.documentdb/databaseaccounts": "2024-11-15",
    "microsoft.eventhub/namespaces": "2024-01-01",
    "microsoft.keyvault/vaults": "2023-07-01",
    "microsoft.operationalinsights/workspaces": "2023-09-01",
    "microsoft.search/searchservices": "2023-11-01",
    "microsoft.storage/storageaccounts": "2023-05-01",
    "microsoft.apimanagement/service": "2022-08-01",
}


def api_version_for(resource_id: str) -> str:
    parts = resource_id.strip("/").lower().split("/")
    if len(parts) == 4 and parts[2] == "resourcegroups":
        return _API_VERSIONS["microsoft.resources/resourcegroups"]
    if "providers" in parts:
        i = len(parts) - 1 - parts[::-1].index("providers")
        tail = parts[i + 1 :]
        if len(tail) == 3:  # provider/type/name
            key = f"{tail[0]}/{tail[1]}"
            if key in _API_VERSIONS:
                return _API_VERSIONS[key]
    raise NeuroSphereError(f"no known api-version for {resource_id}; refusing to delete it")


class ArmDeleter:
    """DELETE through ARM on the host from ``profile_for(cloud).management_url``."""

    def __init__(self, management_url: str, token_provider: Any, client: Any) -> None:
        self._base = management_url.rstrip("/")
        self._token = token_provider
        self._client = client

    async def delete(self, resource_id: str) -> None:
        token = await self._token()
        response = await self._client.delete(
            f"{self._base}{resource_id}",
            params={"api-version": api_version_for(resource_id)},
            headers={"Authorization": f"Bearer {token}"},
        )
        if response.status_code not in (200, 202, 204):
            raise NeuroSphereError(f"ARM delete failed with HTTP {response.status_code}")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    src = p.add_argument_group("register source")
    src.add_argument("--export", type=Path, help="register export JSON file")
    src.add_argument("--cosmos-database")
    src.add_argument("--cosmos-container")
    src.add_argument("--deployment-id", help="deployment to load from the Cosmos store")
    p.add_argument("--dry-run", action="store_true", help="report only; never deletes")
    p.add_argument("--report", type=Path, help="write the JSON report here (default: stdout)")
    p.add_argument("--confirm", help="deployment id; required for real removal")
    return p


async def _load_cosmos(args: argparse.Namespace) -> RegisterExport:
    from neurosphere_core.clients import ClientLifetime, create_cosmos_client
    from neurosphere_core.cloud import load_settings
    from neurosphere_core.deploy.register.cosmos_store import CosmosRegisterStore

    if not (args.cosmos_database and args.cosmos_container and args.deployment_id):
        raise NeuroSphereError("--cosmos-database, --cosmos-container, --deployment-id required")
    settings = load_settings()
    async with ClientLifetime() as lifetime:
        client = create_cosmos_client(
            settings, lifetime=lifetime, account=os.environ.get("NS_COSMOS_ACCOUNT")
        )
        store = CosmosRegisterStore.from_client(
            client, database=args.cosmos_database, container=args.cosmos_container
        )
        return RegisterExport(
            deployment_id=args.deployment_id,
            rows=tuple(await store.list_rows(args.deployment_id)),
            consents=tuple(await store.list_consents(args.deployment_id)),
        )


async def load_register(args: argparse.Namespace) -> RegisterExport:
    if args.export is not None:
        return RegisterExport.model_validate_json(args.export.read_text(encoding="utf-8-sig"))
    return await _load_cosmos(args)


def report_for(plan: RemovalPlan, *, dry_run: bool) -> dict[str, Any]:
    return {
        "deployment_id": plan.deployment_id,
        "dry_run": dry_run,
        "removable": [e.resource_id for e in plan.removable],
        "entries": [e.model_dump(mode="json", exclude_none=True) for e in plan.entries],
    }


def _emit(report: dict[str, Any], target: Path | None) -> None:
    text = json.dumps(report, indent=2)
    if target is None:
        print(text)
    else:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text + "\n", encoding="utf-8")


def _refusal(args: argparse.Namespace, register: RegisterExport) -> str | None:
    if os.environ.get(LIVE_APPROVAL_ENV) != "1":
        return f"real removal refused: {LIVE_APPROVAL_ENV}=1 is required (use --dry-run to preview)"
    if not args.confirm or args.confirm != register.deployment_id:
        return "real removal refused: --confirm must equal the register's deployment id"
    return None


async def _real_removal(rows: Sequence[ResourceRow], register: RegisterExport) -> list[str]:
    import httpx
    from azure.identity.aio import DefaultAzureCredential
    from neurosphere_core.cloud import CloudName, load_settings, profile_for

    settings = load_settings()
    profile = profile_for(settings.cloud or CloudName.COMMERCIAL)
    scope = f"{profile.management_url}.default"
    async with (
        DefaultAzureCredential(authority=profile.login_host) as credential,
        httpx.AsyncClient(timeout=60) as http,
    ):

        async def token() -> str:
            return (await credential.get_token(scope)).token

        return await remove(
            register.deployment_id, rows, ArmDeleter(profile.management_url, token, http)
        )


async def run(args: argparse.Namespace) -> int:
    register = await load_register(args)
    plan = plan_removal(register.deployment_id, register.rows)
    if args.dry_run:
        _emit(report_for(plan, dry_run=True), args.report)
        return 0
    reason = _refusal(args, register)
    if reason is not None:
        print(reason, file=sys.stderr)
        return EXIT_REFUSED
    deleted = await _real_removal(register.rows, register)
    report = report_for(plan, dry_run=False) | {"deleted": deleted}
    _emit(report, args.report)
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    reconfigure = getattr(sys.stdout, "reconfigure", None)
    if reconfigure is not None:
        reconfigure(encoding="utf-8")
    args = build_parser().parse_args(argv)
    if args.export is None and args.deployment_id is None:
        print("provide --export or the Cosmos source options", file=sys.stderr)
        return 2
    try:
        return asyncio.run(run(args))
    except NeuroSphereError as exc:
        print(f"error: {exc.detail or exc.title}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
