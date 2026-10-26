"""Grant the local operator a role over the sandbox domains in the policy store (PRP-29 item 6).

    python scripts/sandbox/sbx_grant_operator.py --object-id <oid> --role admin

Entra app roles only drive navigation display; authority comes from the policy store. Without
this grant a real sign-in shows the pages but every API call answers 403.

Local emulator only: the Cosmos endpoint must be loopback (``sbx_guard``; there is no override).
The principal id is ``HMAC(tenant:oid)`` from the SAME resolver the API uses
(``neurosphere_api.runtime.resolve_pseudonym_key``), so the API finds this document.

Environment (same names as the API): ``NS_ENV`` (default ``local``), ``NS_AUTH_TENANT_ID``,
``NS_AUTH_CUSTOMER_ID`` (default ``synthco``), ``NS_AUTH_PSEUDONYM_KEY[_REFERENCE]`` (optional
locally), ``NS_AUTH_POLICY_CONTAINER``, ``NS_STORE_DATABASE``, ``NS_COSMOS_ENDPOINT`` /
``NS_COSMOS_KEY`` (emulator). Idempotent: a repeated run changes nothing and does not bump the
policy version. Privileged roles are time-bound (C7), so they carry a 30 day expiry that a
re-run renews once less than 7 days remain.
"""

from __future__ import annotations

import argparse
import asyncio
import io
import os
import re
import sys
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Final, Protocol

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
for _path in (HERE, REPO):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from sbx_guard import GuardError, cosmos_settings, require_local_endpoint  # noqa: E402

GUID_RE: Final = re.compile(r"^[0-9a-fA-F]{8}-(?:[0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}$")
EXIT_REFUSED: Final = 2
PRIVILEGED_TTL: Final = timedelta(days=30)
RENEW_WITHIN: Final = timedelta(days=7)
DEFAULT_LOCAL_ENDPOINT: Final = "http://127.0.0.1:8081"
ASSIGNMENT_PREFIX: Final = "operator-"
_VERSION_RE: Final = re.compile(r"^local-(\d+)$")


class PolicyWriter(Protocol):
    async def upsert(self, document: dict[str, Any]) -> None: ...


def sandbox_domain_ids(*, seed: int, profile: str, cloud: str, customer: str) -> tuple[str, ...]:
    """Canonical domain ids of the generated sandbox estate (same plan ``make seed`` loads)."""
    from sandbox.config import PROFILES, GenerateConfig
    from sandbox.world import World

    world = World(
        GenerateConfig(seed=seed, profile=PROFILES[profile], cloud=cloud, customer=customer)
    )
    return tuple(world.domain_id(i) for i in range(len(world.domains)))


def next_version(current: str | None) -> str:
    match = _VERSION_RE.fullmatch(current or "")
    return f"local-{int(match.group(1)) + 1}" if match else "local-1"


async def grant_operator(
    repo: Any,
    writer: PolicyWriter,
    *,
    customer_id: str,
    principal_id: str,
    role: str,
    domain_ids: Sequence[str],
    now: datetime | None = None,
) -> str:
    """Ensure the principal holds ``role`` over ``domain_ids``. Returns ``created``,
    ``updated``, ``renewed`` or ``unchanged`` (nothing written for the last)."""
    from neurosphere_core.auth.scope import PolicyHead, PolicyRoleAssignment, PrincipalPolicy
    from neurosphere_core.auth.scope.permissions import PRIVILEGED_ROLES, Role
    from neurosphere_core.auth.scope.policy import principal_document_id

    moment = now or datetime.now(UTC)
    role_enum = Role(role)
    domains = tuple(sorted(domain_ids))
    assignment_id = ASSIGNMENT_PREFIX + role_enum.value
    expires = moment + PRIVILEGED_TTL if role_enum in PRIVILEGED_ROLES else None

    existing = await repo.get_principal_policy(customer_id, principal_id)
    head = await repo.get_policy_head(customer_id)
    others = (
        tuple(a for a in existing.role_assignments if a.assignment_id != assignment_id)
        if existing
        else ()
    )
    current = (
        next((a for a in existing.role_assignments if a.assignment_id == assignment_id), None)
        if existing
        else None
    )
    members = set(existing.domain_memberships) if existing else set()
    members.update(domains)

    if existing is not None and head is not None and current is not None:
        covered = set(domains) <= set(existing.domain_memberships)
        same = current.role is role_enum and tuple(sorted(current.domain_ids)) == domains
        fresh = current.expires_at is None or current.expires_at - moment > RENEW_WITHIN
        if covered and same and (fresh or expires is None):
            return "unchanged"
        outcome = "renewed" if covered and same else "updated"
    else:
        outcome = "updated" if existing is not None else "created"

    assignment = PolicyRoleAssignment(
        assignment_id=assignment_id,
        role=role_enum,
        domain_ids=domains,
        expires_at=expires,
        reason="local operator grant (sbx_grant_operator)",
    )
    policy = PrincipalPolicy(
        id=principal_document_id(principal_id),
        customer_id=customer_id,
        principal_id=principal_id,
        domain_memberships=tuple(sorted(members)),
        role_assignments=(*others, assignment),
        grants=existing.grants if existing else (),
    )
    await writer.upsert(policy.model_dump(mode="json"))
    new_head = PolicyHead(
        customer_id=customer_id, policy_version=next_version(head.policy_version if head else None)
    )
    await writer.upsert(new_head.model_dump(mode="json"))
    return outcome


class _CosmosWriter:
    def __init__(self, container: Any) -> None:
        self._container = container

    async def upsert(self, document: dict[str, Any]) -> None:
        await self._container.upsert_item(body=document)


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument("--object-id", required=True, help="your Entra object id (az ad signed-in-user)")
    p.add_argument(
        "--role", required=True, help="viewer|analyst|domain_steward|admin|security_auditor"
    )
    p.add_argument("--tenant-id", help="default: NS_AUTH_TENANT_ID")
    p.add_argument("--seed", type=int, default=1)
    p.add_argument("--profile", default="tiny")
    p.add_argument("--cloud", default="commercial", choices=("commercial", "government"))
    return p


def _principal_id(
    *, env: Mapping[str, str], tenant: str, customer: str, cloud: str, object_id: str
) -> str:
    from neurosphere_api.runtime import AuthSettings, resolve_pseudonym_key
    from neurosphere_core.auth.jwt.config import normalize_tenant_id
    from neurosphere_core.auth.scope import PrincipalPseudonymizer
    from neurosphere_core.cloud import CloudName

    key = resolve_pseudonym_key(AuthSettings(), env=env.get("NS_ENV", "local"))
    return PrincipalPseudonymizer(key).principal_id(
        cloud=CloudName(cloud),
        customer_id=customer,
        tenant_id=normalize_tenant_id(tenant),
        object_id=object_id,
        kind="user",
    )


async def _run_real(env: Mapping[str, str], endpoint: str, key: str, **grant: Any) -> str:
    from azure.cosmos.aio import CosmosClient
    from neurosphere_core.auth.scope import CosmosPolicyRepository
    from neurosphere_core.stores import DEFAULT_DATABASE

    database = env.get("NS_STORE_DATABASE", DEFAULT_DATABASE)
    container = env.get("NS_AUTH_POLICY_CONTAINER", "policy")
    async with CosmosClient(endpoint, key, enable_endpoint_discovery=False) as client:
        repo = CosmosPolicyRepository(client, database=database, container=container)
        writer = _CosmosWriter(client.get_database_client(database).get_container_client(container))
        return await grant_operator(repo, writer, **grant)


def main(argv: Sequence[str] | None = None, *, env: Mapping[str, str] | None = None) -> int:
    args = _parser().parse_args(argv)
    environ = dict(os.environ) if env is None else dict(env)
    try:
        endpoint = require_local_endpoint(
            environ.get("NS_COSMOS_ENDPOINT")
            or environ.get("NS_SANDBOX_COSMOS_ENDPOINT")
            or DEFAULT_LOCAL_ENDPOINT
        )
        key = environ.get("NS_COSMOS_KEY") or cosmos_settings({})[1]
    except GuardError as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return EXIT_REFUSED
    tenant = args.tenant_id or environ.get("NS_AUTH_TENANT_ID", "")
    if GUID_RE.fullmatch(args.object_id) is None or GUID_RE.fullmatch(tenant) is None:
        print(
            "ERROR: --object-id and the tenant (NS_AUTH_TENANT_ID) must be GUIDs.", file=sys.stderr
        )
        return EXIT_REFUSED
    customer = environ.get("NS_AUTH_CUSTOMER_ID", "synthco")
    try:
        principal_id = _principal_id(
            env=environ,
            tenant=tenant,
            customer=customer,
            cloud=args.cloud,
            object_id=args.object_id,
        )
        domains = sandbox_domain_ids(
            seed=args.seed, profile=args.profile, cloud=args.cloud, customer=customer
        )
        outcome = asyncio.run(
            _run_real(
                environ,
                endpoint,
                key,
                customer_id=customer,
                principal_id=principal_id,
                role=args.role,
                domain_ids=domains,
            )
        )
    except (ValueError, KeyError) as exc:
        print(f"ERROR: {type(exc).__name__}: invalid role, profile or identifier.", file=sys.stderr)
        return EXIT_REFUSED
    print(f"operator grant {outcome}: role={args.role} domains={len(domains)} customer={customer}")
    return 0


if __name__ == "__main__":
    if isinstance(sys.stdout, io.TextIOWrapper):
        sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
