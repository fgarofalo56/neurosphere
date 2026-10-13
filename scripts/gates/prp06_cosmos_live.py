"""PRP-06 live run: audit, policy and revocation stores against a real Commercial Cosmos account.

Operator-approved only. Refuses unless NS_LIVE_APPROVED=1 (checked first, before any import of
project code or network access).

Environment:
  NS_LIVE_APPROVED=1          required approval gate
  NS_P06_COSMOS_ENDPOINT      https://<account>.documents.azure.com:443/ (Commercial only)
  NS_P06_DATABASE             database name (default ns_gate)

Preconditions, provisioned by the operator with `az` (this script creates no resources):
  containers  audit (/chain_id), audit_tail (/chain_id), policy (/customer_id),
              revocations (/principal_id, default TTL on)
  data-plane RBAC for the signed-in identity, and NO account-wide data contributor role:
    - items/read, items/create, executeQuery on the database
    - items/replace on audit_tail, policy and revocations only
  so the audit records container is append-only for this identity at the service.

Auth is Entra only (DefaultAzureCredential). No key or connection string is accepted.
Writes docs/evidence/PRP-06/live-cosmos-<date>.md. It records outcomes only, never document
content, identities or tokens.
"""

from __future__ import annotations

import asyncio
import os
import sys
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import urlparse

REPO = Path(__file__).resolve().parents[2]
Row = tuple[str, str, bool]


def _refuse() -> int:
    print(
        "REFUSED: prp06_cosmos_live.py needs operator approval; set NS_LIVE_APPROVED=1. "
        "No connection was attempted.",
        file=sys.stderr,
    )
    return 2


async def _status_of(coro: object) -> str:
    from azure.cosmos.exceptions import CosmosHttpResponseError

    try:
        await coro  # type: ignore[misc]
    except CosmosHttpResponseError as exc:
        return f"HTTP {exc.status_code}"
    except Exception as exc:
        return type(exc).__name__
    return "ALLOWED"


async def _run(endpoint: str, database: str) -> list[Row]:
    from azure.cosmos.aio import CosmosClient
    from azure.identity.aio import DefaultAzureCredential

    sys.path.insert(0, str(REPO / "packages" / "core"))
    from neurosphere_contracts.scope.v1.identity_scope import IdentityScope as ContractScope
    from neurosphere_core.audit import (
        AuditContext,
        AuditRepository,
        build_after,
        build_allowed,
        build_before,
        build_denied,
        make_subject,
    )
    from neurosphere_core.audit.cosmos_store import CosmosAuditStore
    from neurosphere_core.auth.revocation.cosmos_store import CosmosRevocationStore
    from neurosphere_core.auth.revocation.model import RevocationEntry
    from neurosphere_core.auth.scope.cosmos_repository import CosmosPolicyRepository
    from neurosphere_core.scope import IdentityScope

    rows: list[Row] = []
    run = uuid.uuid4().hex[:10]
    chain = f"gate{run}.domain-live"
    target = "commercial:gate:foundry:model_deployment:eastus2/chat-live"
    scope_hash = "sha256:" + "0" * 64
    scope = IdentityScope._from_verified_contract(  # pyright: ignore[reportPrivateUsage]
        ContractScope.model_validate(
            {
                "schema_version": "1.0.0",
                "cloud": "commercial",
                "customer_id": f"gate{run}",
                "principal": {
                    "principal_id": f"commercial:gate{run}:entra:person:psn_0123456789abcdef",
                    "principal_pseudonym": "p-7f3a9c21",
                    "principal_kind": "user",
                },
                "roles": [],
                "allowed_domains": [f"commercial:gate{run}:catalog:domain:live"],
                "allowed_resources": [],
                "policy_version": "v1",
                "derived_at": "2026-10-13T00:00:00Z",
                "scope_hash": scope_hash,
            }
        )
    )
    ctx = AuditContext.from_scope(
        scope, correlation_id="corr-live-gate", operation="action.execute", channel="rest"
    )

    async with (
        DefaultAzureCredential() as credential,
        CosmosClient(endpoint, credential=credential) as client,
    ):
        # --- audit: parallel writers, chain verify
        store = CosmosAuditStore.from_client(
            client, database=database, container="audit", tail_container="audit_tail"
        )
        writers = [AuditRepository(store) for _ in range(4)]
        drafts = []
        for i in range(12):
            subj = make_subject(
                target, "model_deployment", target_version=f"etag-{i}", state={"v": i}
            )
            drafts.append(
                [
                    build_before(ctx, subj),
                    build_after(ctx, subj, result="succeeded", verified=True),
                    build_denied(ctx, code="forbidden", reason="domain_out_of_scope"),
                    build_allowed(ctx, subj),
                ][i % 4]
            )
        await asyncio.gather(
            *(w.append(chain, d) for w, d in zip(writers * 3, drafts, strict=True))
        )
        records = await writers[0].read_range(chain, limit=500)
        verified = await writers[0].verify(chain)
        rows.append(
            (
                "audit: 4 parallel writers, 12 appends, chain verifies",
                f"records={len(records)} "
                f"sequences_contiguous={[r.sequence for r in records] == list(range(12))} "
                f"verify_ok={verified.ok}",
                len(records) == 12 and verified.ok,
            )
        )

        # --- audit: service-side immutability of the records container
        audit = client.get_database_client(database).get_container_client("audit")
        body = {"id": "rec-0", "chain_id": chain, "doc_type": "audit_record", "sequence": 0, "x": 1}
        for name, call in (
            ("replace_item", audit.replace_item(item="rec-0", body=body)),
            ("upsert_item", audit.upsert_item(body=body)),
            ("delete_item", audit.delete_item(item="rec-0", partition_key=chain)),
            (
                "patch_item",
                audit.patch_item(
                    item="rec-0",
                    partition_key=chain,
                    patch_operations=[{"op": "set", "path": "/x", "value": 2}],
                ),
            ),
        ):
            got = await _status_of(call)
            rows.append((f"audit records: {name} refused by the service", got, got == "HTTP 403"))
        after = await writers[0].verify(chain)
        rows.append(
            (
                "audit: chain still verifies after the refused mutations",
                f"verify_ok={after.ok} records_checked={after.records_checked}",
                after.ok and after.records_checked == 12,
            )
        )

        # --- policy store: seed with create, read through the repository
        policy = client.get_database_client(database).get_container_client("policy")
        customer = f"gate{run}"
        pid = f"commercial:{customer}:entra:person:p-{'a' * 64}"
        suffix = pid.rsplit(":", 1)[-1]
        await policy.create_item(
            body={
                "id": "policy-head",
                "doc_type": "policy_head",
                "customer_id": customer,
                "policy_version": "v1",
            }
        )
        await policy.create_item(
            body={
                "id": f"principal.{suffix}",
                "doc_type": "principal_policy",
                "customer_id": customer,
                "principal_id": pid,
                "domain_memberships": [],
                "role_assignments": [],
                "grants": [],
            }
        )
        repo = CosmosPolicyRepository(client, database=database)
        head = await repo.get_policy_head(customer)
        doc = await repo.get_principal_policy(customer, pid)
        missing = await repo.get_principal_policy(
            customer, f"commercial:{customer}:entra:person:p-{'b' * 64}"
        )
        rows.append(
            (
                "policy: head and principal read via CosmosPolicyRepository; absent doc is None",
                f"head={'ok' if head and head.policy_version == 'v1' else 'BAD'} "
                f"principal={'ok' if doc and doc.principal_id == pid else 'BAD'} "
                f"absent_is_none={missing is None}",
                bool(head) and bool(doc) and missing is None,
            )
        )

        # --- revocation store: put/get, newer entry wins
        rev = CosmosRevocationStore.from_client(client, database=database, container="revocations")
        who = f"commercial:{customer}:entra:person:p-{'c' * 64}"
        admin = f"commercial:{customer}:entra:person:p-{'d' * 64}"
        t0 = datetime.now(UTC)
        first = RevocationEntry(
            principal_id=who, revoked_at=t0, reason="admin_revoke", revoked_by=admin
        )
        await rev.put(first)
        got = await rev.get(who)
        later = RevocationEntry(
            principal_id=who,
            revoked_at=t0 + timedelta(seconds=30),
            reason="admin_revoke",
            revoked_by=admin,
        )
        kept = await rev.put(later)
        rows.append(
            (
                "revocation: put/get round trip; a later revocation replaces the earlier one",
                f"read_back={got is not None and got.principal_id == who} "
                f"newer_kept={kept.revoked_at == later.revoked_at}",
                got is not None and kept.revoked_at == later.revoked_at,
            )
        )
    return rows


def main() -> int:
    if os.environ.get("NS_LIVE_APPROVED") != "1":
        return _refuse()
    endpoint = os.environ.get("NS_P06_COSMOS_ENDPOINT", "").strip()
    database = os.environ.get("NS_P06_DATABASE", "ns_gate").strip()
    host = (urlparse(endpoint).hostname or "").lower()
    if not endpoint.startswith("https://") or not host.endswith(".documents.azure.com"):
        print(
            "ERROR: NS_P06_COSMOS_ENDPOINT must be a Commercial "
            "https://<account>.documents.azure.com endpoint (Government is refused).",
            file=sys.stderr,
        )
        return 2

    rows = asyncio.run(_run(endpoint, database))
    today = datetime.now(UTC).date().isoformat()
    out = REPO / "docs" / "evidence" / "PRP-06" / f"live-cosmos-{today}.md"
    ok = all(p for _, _, p in rows)
    lines = [
        f"# PRP-06 live Cosmos run ({today})",
        "",
        "Operator-approved live run (NS_LIVE_APPROVED=1) against a throwaway serverless Commercial",
        "Cosmos NoSQL account, Entra auth only. Outcomes only: no document content or identities.",
        "",
        "| Check | Outcome | Pass |",
        "|---|---|---|",
        *[f"| {n} | {o} | {'yes' if p else 'NO'} |" for n, o, p in rows],
        "",
        "Scope of the immutability result: the 403s prove the SERVICE refuses replace, upsert,",
        "patch and delete on the audit records container for this identity, because its role",
        "grants only",
        "create/read/query there. It is not a WORM guarantee: an account owner or anyone holding a",
        "broader data-plane or control-plane role can still change data, so the hash chain remains",
        "the tamper-detection control. Not a compliance, ATO or FedRAMP claim.",
        "",
    ]
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines), encoding="utf-8")
    for n, o, p in rows:
        print(f"{'PASS' if p else 'FAIL'}  {n}: {o}")
    print(f"evidence: {out.relative_to(REPO)}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
