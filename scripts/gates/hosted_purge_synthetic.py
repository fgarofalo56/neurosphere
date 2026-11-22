"""Purge the synthetic estate from a hosted real-tenant environment (PRP-139 item 2).

    NS_LIVE_APPROVED=1 NS_ENV=prod NS_SANDBOX_HOSTED_DEPLOYMENT_ID=<id> \
      uv run python scripts/gates/hosted_purge_synthetic.py plan [--include-audit]
    NS_LIVE_APPROVED=1 NS_ENV=prod NS_SANDBOX_HOSTED_DEPLOYMENT_ID=<id> \
      uv run python scripts/gates/hosted_purge_synthetic.py apply --confirm <id> [--include-audit]

``plan`` is read-only: it counts, per container, what ``apply`` would delete and writes a plan
file (with a content hash) under ``temp/hosted-demo/``. ``apply`` needs ``NS_LIVE_APPROVED=1``,
``--confirm <deployment id>``, a plan younger than 24 hours whose counts still match, a hosted
environment already running in ``real-tenant`` mode under a customer id other than the one being
purged, and re-reads and re-tests every document immediately before deleting it. It stops at the
first document that fails the test.

What is synthetic is decided by one pure function, :func:`is_synthetic`, over a closed rule table
(PRP-139 clarification 4): the purge customer (``synthco`` unless the registration's
``previous_customer_id`` says otherwise) AND the ``sandbox`` source, or one of the seed's own
fixed records. A container the table does not name is never opened. Audit chains are kept unless
``--include-audit``. Event Hubs is not purged. Evidence under ``docs/evidence/PRP-139/`` holds
counts only: no id, host, GUID or token.

Exit 0 = done, 1 = a step failed (or an unexpected document stopped the purge), 2 = refused
(nothing was contacted, or nothing was deleted).
"""

from __future__ import annotations

import argparse
import hashlib
import importlib
import io
import json
import os
import re
import sys
import uuid
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any, Final, Protocol
from urllib.parse import urlsplit

REPO: Final = Path(__file__).resolve().parents[2]
SANDBOX_SCRIPTS: Final = REPO / "scripts" / "sandbox"
STACK_FIXTURES: Final = REPO / "sandbox" / "stack"
DEFAULT_REGISTRATION: Final = REPO / "temp" / "hosted-demo" / "registration.json"
PLAN_DIR: Final = REPO / "temp" / "hosted-demo"
PLAN_NAME: Final = "purge-plan.json"
EVIDENCE_DIR: Final = REPO / "docs" / "evidence" / "PRP-139"
EXIT_FAILED: Final = 1
EXIT_REFUSED: Final = 2
PLAN_MAX_AGE: Final = timedelta(hours=24)
DEFAULT_BATCH: Final = 50
MAX_BATCH: Final = 200

DEFAULT_PURGE_CUSTOMER: Final = "synthco"
SYNTHETIC_SOURCE: Final = "sandbox"
ARCHIVE: Final = "archive"

# -- the closed rule table ---------------------------------------------------------------------
#: Customer AND source ``sandbox`` (ids of the form ``<cloud>:<customer>:sandbox:...``).
SOURCE_CONTAINERS: Final = (
    "catalog",
    "aggregates",
    "cost-ledger",
    "outbox",
    "outbox-checkpoints",
    "ingestion-accepted",
    "ingestion-watermarks",
)
#: The seed's own fixed, sourceless records (grants, snapshot, gateway, reports, intents, ...).
SEED_CONTAINERS: Final = (
    "policy",
    "price_snapshots",
    "gateways",
    "reports",
    "action_intents",
    "recommendations",
    "evaluation_runs",
    "evaluation_results",
    "mcp_servers",
)
#: Only with ``--include-audit``.
AUDIT_CONTAINERS: Final = ("audit", "audit_tail")
#: Every name the purge may open. Anything else is never opened.
RULE_CONTAINERS: Final = (*SOURCE_CONTAINERS, *SEED_CONTAINERS, *AUDIT_CONTAINERS, ARCHIVE)

#: Constants the seed writes (sbx_seed_stack, sbx_grant_operator, sandbox.config);
#: a test asserts each still matches its source.
SEED_PRICE_SNAPSHOT_ID: Final = "sandbox-prices-2026-10"
SEED_RUN_PREFIX: Final = "seed-offline-"
SEED_ASSIGNMENT_PREFIX: Final = "operator-"
SEED_CREATED_AT_PREFIX: Final = "2026-10-19T12:00:00"
SEED_GATEWAY_ARM_ID: Final = (
    "/subscriptions/00000000-0000-4000-8000-000000000001/resourceGroups/rg-synthetic-sandbox"
    "/providers/Microsoft.ApiManagement/service/apim-synthetic-sandbox"
)
_POLICY_VERSION_RE: Final = re.compile(r"local-\d+")

Doc = dict[str, Any]


@dataclass(frozen=True)
class SeedMarkers:
    """Deterministic identifiers the seed computes, recomputed here from its fixtures."""

    report_ids: frozenset[str] = frozenset()
    intent_keys: frozenset[str] = frozenset()
    mcp_hosts: frozenset[str] = frozenset()


def _fixture(name: str) -> Doc:
    return json.loads((STACK_FIXTURES / name).read_text(encoding="utf-8"))


@lru_cache(maxsize=16)
def seed_markers(purge_customer: str) -> SeedMarkers:
    """The seed's report ids, intent idempotency keys and MCP hosts for ``purge_customer``."""
    reports = _fixture("reports.json")
    slugs = [s["slug"] for s in (*reports["reports"], *reports.get("operator_reports", ()))]
    report_ids = frozenset(
        str(uuid.uuid5(uuid.NAMESPACE_URL, f"neurosphere:{purge_customer}:{slug}"))
        for slug in slugs
    )
    intent_keys = frozenset("seed-intent-" + s["slug"] for s in _fixture("intents.json")["intents"])
    hosts = frozenset(
        (urlsplit(s["url"]).hostname or "").lower() for s in _fixture("mcp_servers.json")["servers"]
    )
    return SeedMarkers(report_ids, intent_keys, hosts - {""})


def _customer_of(document: Mapping[str, Any]) -> str | None:
    value = document.get("customer_id")
    if isinstance(value, str) and value:
        return value
    ident = document.get("id")
    if isinstance(ident, str):
        parts = ident.split(":")
        if len(parts) >= 3:
            return parts[1]
    return None


def _is_sandbox_source(document: Mapping[str, Any]) -> bool:
    source = document.get("source")
    if isinstance(source, str) and source:
        return source == SYNTHETIC_SOURCE
    ident = document.get("id")
    parts = ident.split(":") if isinstance(ident, str) else []
    return len(parts) >= 3 and parts[2] == SYNTHETIC_SOURCE


def _policy_is_synthetic(document: Mapping[str, Any]) -> bool:
    if document.get("doc_type") == "policy_head":
        return _POLICY_VERSION_RE.fullmatch(str(document.get("policy_version", ""))) is not None
    assignments = document.get("role_assignments")
    if not isinstance(assignments, list) or not assignments:
        return False
    return all(
        isinstance(a, Mapping)
        and str(a.get("assignment_id", "")).startswith(SEED_ASSIGNMENT_PREFIX)  # pyright: ignore[reportUnknownMemberType, reportUnknownArgumentType]
        for a in assignments  # pyright: ignore[reportUnknownVariableType]
    )


def is_synthetic(container: str, document: Mapping[str, Any], purge_customer: str) -> bool:
    """True only for a document the closed rule table names. Pure: no I/O, no clock.

    A container that is not in :data:`RULE_CONTAINERS` is never synthetic. Every rule but the
    two global ones (price snapshots, MCP servers, archive) also needs the purge customer.
    """
    if not purge_customer:
        return False
    if container == ARCHIVE:
        name = document.get("name")
        return isinstance(name, str) and name.startswith(purge_customer + "/")
    if container == "price_snapshots":
        return document.get("id") == SEED_PRICE_SNAPSHOT_ID and document.get("synthetic") is True
    if container == "mcp_servers":
        host = urlsplit(str(document.get("url", ""))).hostname or ""
        return host.lower() in seed_markers(purge_customer).mcp_hosts
    if container not in RULE_CONTAINERS:
        return False
    if _customer_of(document) != purge_customer:
        return False
    if container in SOURCE_CONTAINERS:
        return _is_sandbox_source(document)
    markers = seed_markers(purge_customer)
    if container == "policy":
        return _policy_is_synthetic(document)
    if container == "gateways":
        return document.get("arm_resource_id") == SEED_GATEWAY_ARM_ID
    if container == "reports":
        return document.get("id") in markers.report_ids
    if container == "action_intents":
        return document.get("idempotency_key") in markers.intent_keys
    if container == "recommendations":
        return str(document.get("created_at", "")).startswith(SEED_CREATED_AT_PREFIX)
    if container in ("evaluation_runs", "evaluation_results"):
        return str(document.get("run_id", "")).startswith(SEED_RUN_PREFIX)
    if container in AUDIT_CONTAINERS:
        return True  # customer already matched; the caller only opens these with include_audit
    return False


def containers_for(include_audit: bool) -> tuple[str, ...]:
    return (
        *SOURCE_CONTAINERS,
        *SEED_CONTAINERS,
        *(AUDIT_CONTAINERS if include_audit else ()),
        ARCHIVE,
    )


# -- stores (small protocols; tests use in-memory twins) ----------------------------------------


class DocumentStore(Protocol):
    def scan(self, container: str, purge_customer: str) -> Iterable[Doc]:
        """Documents that may belong to ``purge_customer`` (a superset is allowed)."""
        ...

    def fetch(self, container: str, doc_id: str) -> Doc | None:
        """One document by id (the price snapshot container is keyed by snapshot id)."""
        ...

    def reread(self, container: str, document: Mapping[str, Any]) -> Doc | None:
        """The stored document with the same id and partition, or ``None`` when gone."""
        ...

    def delete(self, container: str, document: Mapping[str, Any]) -> None: ...


class BlobStore(Protocol):
    def list_prefix(self, prefix: str) -> Iterable[str]: ...

    def delete(self, name: str) -> None: ...


@dataclass
class Stores:
    documents: DocumentStore
    blobs: BlobStore
    closers: list[Callable[[], None]] = field(default_factory=lambda: [])

    def close(self) -> None:
        for closer in self.closers:
            closer()


Counts = dict[str, dict[str, int]]


def _archive_docs(blobs: BlobStore, purge_customer: str) -> list[Doc]:
    return [{"name": name} for name in blobs.list_prefix(purge_customer + "/")]


def count_selection(
    stores: Stores, purge_customer: str, include_audit: bool
) -> tuple[Counts, dict[str, list[Doc]]]:
    """Scan once: the documents ``is_synthetic`` accepts, and per-container ``selected`` and
    ``kept`` counts. Opens only rule-table containers; scanned non-synthetic ones are ``kept``."""
    chosen: dict[str, list[Doc]] = {}
    counts: Counts = {}
    for container in containers_for(include_audit):
        if container == ARCHIVE:
            found = _archive_docs(stores.blobs, purge_customer)
        elif container == "price_snapshots":
            single = stores.documents.fetch(container, SEED_PRICE_SNAPSHOT_ID)
            found = [single] if single is not None else []
        else:
            found = list(stores.documents.scan(container, purge_customer))
        picked = [d for d in found if is_synthetic(container, d, purge_customer)]
        chosen[container] = picked
        counts[container] = {"selected": len(picked), "kept": len(found) - len(picked)}
    return counts, chosen


# -- plan file ---------------------------------------------------------------------------------


def _hash_plan(body: Mapping[str, Any]) -> str:
    text = json.dumps(body, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def build_plan(
    *, deployment_id: str, purge_customer: str, include_audit: bool, counts: Counts, now: datetime
) -> Doc:
    body: Doc = {
        "gate": "hosted_purge_synthetic",
        "created": now.astimezone(UTC).isoformat(),
        "deployment_id": deployment_id,
        "purge_customer": purge_customer,
        "include_audit": include_audit,
        "counts": counts,
    }
    return {**body, "content_hash": _hash_plan(body)}


def read_plan(
    path: Path,
    *,
    deployment_id: str,
    purge_customer: str,
    include_audit: bool,
    now: datetime,
) -> tuple[Doc | None, str | None]:
    """The plan and no reason, or ``None`` and the refusal reason."""
    try:
        plan = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None, "no readable plan file; run `plan` first"
    if not isinstance(plan, dict):
        return None, "the plan file is not a JSON object"
    body = {k: v for k, v in plan.items() if k != "content_hash"}  # pyright: ignore[reportUnknownVariableType]
    if plan.get("content_hash") != _hash_plan(body):  # pyright: ignore[reportUnknownMemberType]
        return None, "the plan file content hash does not match; it was edited"
    try:
        created = datetime.fromisoformat(str(plan.get("created")))  # pyright: ignore[reportUnknownMemberType]
    except ValueError:
        return None, "the plan file has no valid creation time"
    if (
        created.tzinfo is None
        or now - created > PLAN_MAX_AGE
        or created > now + timedelta(minutes=5)
    ):
        return None, "the plan is older than 24 hours; run `plan` again"
    if (
        plan.get("deployment_id") != deployment_id  # pyright: ignore[reportUnknownMemberType]
        or plan.get("purge_customer") != purge_customer  # pyright: ignore[reportUnknownMemberType]
        or plan.get("include_audit") is not include_audit  # pyright: ignore[reportUnknownMemberType]
    ):
        return None, "the plan was written for another deployment, customer or audit setting"
    return plan, None  # pyright: ignore[reportUnknownVariableType]


# -- evidence (counts only) --------------------------------------------------------------------


def write_evidence(
    evidence_dir: Path,
    *,
    kind: str,
    counts: Mapping[str, Mapping[str, int]],
    now: datetime,
    failure: str | None = None,
) -> Path:
    """``<date>-purge-plan.json`` or ``<date>-purge.json``: container names and counts only."""
    evidence_dir.mkdir(parents=True, exist_ok=True)
    doc: dict[str, Any] = {
        "gate": "hosted_purge_synthetic",
        "kind": kind,
        "recorded": now.astimezone(UTC).strftime("%Y-%m-%d"),
        "counts": {name: dict(sorted(c.items())) for name, c in sorted(counts.items())},
    }
    if failure is not None:
        doc["reason"] = "delete_failed"
        doc["error_class"] = failure
    suffix = "purge-plan" if kind == "plan" else "purge"
    path = evidence_dir / f"{doc['recorded']}-{suffix}.json"
    path.write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


# -- apply -------------------------------------------------------------------------------------


@dataclass
class ApplyResult:
    counts: Counts
    stopped: bool = False
    failure: str | None = None  # exception class name of a failed delete; never its message


def apply_purge(
    stores: Stores,
    chosen: Mapping[str, Sequence[Doc]],
    *,
    purge_customer: str,
    kept: Mapping[str, int],
    batch_size: int,
) -> ApplyResult:
    """Delete in bounded batches. Each document is re-read and re-tested right before deletion;
    one that is gone is ``skipped``; one that fails the test stops the purge."""
    result = ApplyResult(
        counts={c: {"deleted": 0, "kept": kept.get(c, 0), "skipped": 0} for c in chosen}
    )
    for container, docs in chosen.items():
        for start in range(0, len(docs), batch_size):
            for doc in docs[start : start + batch_size]:
                current = _reread(stores, container, doc)
                if current is None:
                    result.counts[container]["skipped"] += 1
                    continue
                if not is_synthetic(container, current, purge_customer):
                    result.counts[container]["kept"] += 1
                    result.stopped = True
                    return result
                try:
                    _delete(stores, container, current)
                except Exception as exc:
                    result.failure = type(exc).__name__
                    result.stopped = True
                    return result
                result.counts[container]["deleted"] += 1
    return result


def _reread(stores: Stores, container: str, doc: Mapping[str, Any]) -> Doc | None:
    if container == ARCHIVE:
        name = doc.get("name")
        names = list(stores.blobs.list_prefix(str(name))) if isinstance(name, str) else []
        return {"name": name} if name in names else None
    return stores.documents.reread(container, doc)


def _delete(stores: Stores, container: str, doc: Mapping[str, Any]) -> None:
    if container == ARCHIVE:
        stores.blobs.delete(str(doc["name"]))
    else:
        stores.documents.delete(container, doc)


# -- CLI ---------------------------------------------------------------------------------------


def _refuse(message: str) -> int:
    print(f"REFUSED: {message}", file=sys.stderr)
    return EXIT_REFUSED


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Purge the synthetic estate (PRP-139).")
    parser.add_argument("--registration", type=Path, default=DEFAULT_REGISTRATION)
    parser.add_argument("--plan-file", type=Path, default=PLAN_DIR / PLAN_NAME)
    parser.add_argument("--evidence-dir", type=Path, default=EVIDENCE_DIR)
    parser.add_argument("--include-audit", action="store_true", help="also purge audit chains")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("plan", help="count what apply would delete; deletes nothing")
    apply = sub.add_parser("apply", help="delete what the plan counted")
    apply.add_argument("--confirm", default="", help="the registered deployment id")
    apply.add_argument("--batch-size", type=int, default=DEFAULT_BATCH)
    return parser


def _load_guard() -> Any:
    for path in (SANDBOX_SCRIPTS, REPO):
        if str(path) not in sys.path:
            sys.path.insert(0, str(path))
    return importlib.import_module("sbx_guard")


def _checks(
    args: argparse.Namespace, environ: Mapping[str, str]
) -> tuple[Doc | None, str | None, str]:
    """Registration, a refusal message, and the purge customer. Pure file reads, no network."""
    if environ.get("NS_LIVE_APPROVED") != "1":
        return (
            None,
            "this reads a hosted Azure environment and needs operator approval; set "
            "NS_LIVE_APPROVED=1. Nothing was contacted.",
            "",
        )
    try:
        doc = json.loads(Path(args.registration).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None, "the registration file is missing or not valid JSON.", ""
    if not isinstance(doc, dict):
        return None, "the registration is not a JSON object.", ""
    deployment_id = doc.get("deployment_id")  # pyright: ignore[reportUnknownMemberType]
    if not isinstance(deployment_id, str) or not deployment_id:
        return None, "the registration records no deployment id.", ""
    if args.command == "apply" and args.confirm != deployment_id:
        return None, "--confirm must equal the registered deployment id.", ""
    if doc.get("data_mode") != "real-tenant":  # pyright: ignore[reportUnknownMemberType]
        return (
            None,
            "the active data mode is not real-tenant; redeploy with real-tenant first, so the "
            "app is never blank with nothing behind it.",
            "",
        )
    active_customer = doc.get("customer_id")  # pyright: ignore[reportUnknownMemberType]
    if not isinstance(active_customer, str) or not active_customer:
        return None, "the registration records no customer_id.", ""
    purge_customer = str(doc.get("previous_customer_id") or DEFAULT_PURGE_CUSTOMER)  # pyright: ignore[reportUnknownMemberType]
    if purge_customer == active_customer:
        return None, "the purge customer is the deployment's active customer id.", ""
    return doc, None, purge_customer  # pyright: ignore[reportUnknownVariableType]


def _open_real_stores(registration: Mapping[str, Any]) -> Stores:
    """Entra clients over the registered private endpoints. Imported only after every refusal."""
    from azure.cosmos import CosmosClient
    from azure.identity import DefaultAzureCredential
    from azure.storage.blob import ContainerClient
    from neurosphere_core.stores.containers import CONTAINERS

    credential = DefaultAzureCredential()
    cosmos = CosmosClient(
        f"https://{registration['cosmos_host']}/",
        credential=credential,
        enable_endpoint_discovery=False,
    )
    database = cosmos.get_database_client(str(registration["database"]))
    archive = ContainerClient(
        f"https://{registration['blob_host']}/",
        str(registration["archive_container"]),
        credential=credential,
    )
    paths = {spec.name: tuple(spec.partition_key_paths) for spec in CONTAINERS}
    return Stores(
        documents=_CosmosDocuments(database, paths),
        blobs=_ArchiveBlobs(archive),
        closers=[archive.close, cosmos.close, credential.close],
    )


class _CosmosDocuments:
    def __init__(self, database: Any, paths: Mapping[str, tuple[str, ...]]) -> None:
        self._db = database
        self._paths = paths

    def _proxy(self, container: str) -> Any:
        if container not in RULE_CONTAINERS:
            raise ValueError("container is not in the purge rule table")
        return self._db.get_container_client(container)

    def _key(self, container: str, doc: Mapping[str, Any]) -> Any:
        keys = [doc[p.lstrip("/")] for p in self._paths[container]]
        return keys if len(keys) > 1 else keys[0]

    def scan(self, container: str, purge_customer: str) -> Iterable[Doc]:
        if container == "mcp_servers":
            query, params = "SELECT * FROM c", []
        elif container in SOURCE_CONTAINERS:
            query = "SELECT * FROM c WHERE c.customer_id = @c OR CONTAINS(c.id, @seg)"
            params = [
                {"name": "@c", "value": purge_customer},
                {"name": "@seg", "value": f":{purge_customer}:{SYNTHETIC_SOURCE}:"},
            ]
        elif container in AUDIT_CONTAINERS:
            query = "SELECT * FROM c WHERE c.customer_id = @c OR CONTAINS(c.chain_id, @seg)"
            params = [
                {"name": "@c", "value": purge_customer},
                {"name": "@seg", "value": f":{purge_customer}:"},
            ]
        else:
            query = "SELECT * FROM c WHERE c.customer_id = @c"
            params = [{"name": "@c", "value": purge_customer}]
        return list(
            self._proxy(container).query_items(
                query=query, parameters=params, enable_cross_partition_query=True
            )
        )

    def fetch(self, container: str, doc_id: str) -> Doc | None:
        from azure.cosmos.exceptions import CosmosResourceNotFoundError

        try:
            return self._proxy(container).read_item(item=doc_id, partition_key=doc_id)
        except CosmosResourceNotFoundError:
            return None

    def reread(self, container: str, document: Mapping[str, Any]) -> Doc | None:
        from azure.cosmos.exceptions import CosmosResourceNotFoundError

        try:
            return self._proxy(container).read_item(
                item=document["id"], partition_key=self._key(container, document)
            )
        except CosmosResourceNotFoundError:
            return None

    def delete(self, container: str, document: Mapping[str, Any]) -> None:
        self._proxy(container).delete_item(
            item=document["id"], partition_key=self._key(container, document)
        )


class _ArchiveBlobs:
    def __init__(self, client: Any) -> None:
        self._client = client

    def list_prefix(self, prefix: str) -> Iterable[str]:
        return [b.name for b in self._client.list_blobs(name_starts_with=prefix)]

    def delete(self, name: str) -> None:
        self._client.delete_blob(name)


StoresFactory = Callable[[Mapping[str, Any]], Stores]


def main(
    argv: Sequence[str] | None = None,
    *,
    env: Mapping[str, str] | None = None,
    stores_factory: StoresFactory | None = None,
    now: datetime | None = None,
) -> int:
    environ = dict(os.environ) if env is None else dict(env)
    args = build_parser().parse_args(argv)
    registration, refusal, purge_customer = _checks(args, environ)
    if refusal is not None or registration is None:
        return _refuse(refusal or "refused")
    guard = _load_guard()
    try:
        for kind, name in (
            ("cosmos", "cosmos_host"),
            ("blob", "blob_host"),
        ):
            guard.require_hosted_endpoint(
                f"https://{registration.get(name)}",
                kind=kind,
                env=environ,
                registration_path=args.registration,
            )
    except guard.GuardError as exc:
        return _refuse(str(exc))

    moment = now or datetime.now(UTC)
    deployment_id = str(registration["deployment_id"])
    if args.command == "apply":
        if not 1 <= args.batch_size <= MAX_BATCH:
            return _refuse(f"--batch-size must be between 1 and {MAX_BATCH}")
        plan, why = read_plan(
            args.plan_file,
            deployment_id=deployment_id,
            purge_customer=purge_customer,
            include_audit=args.include_audit,
            now=moment,
        )
        if plan is None:
            return _refuse(why or "no valid plan")
    else:
        plan = None

    factory = stores_factory or _open_real_stores
    stores = factory(registration)
    try:
        counts, chosen = count_selection(stores, purge_customer, args.include_audit)
        if args.command == "plan":
            built = build_plan(
                deployment_id=deployment_id,
                purge_customer=purge_customer,
                include_audit=args.include_audit,
                counts=counts,
                now=moment,
            )
            args.plan_file.parent.mkdir(parents=True, exist_ok=True)
            args.plan_file.write_text(json.dumps(built, indent=2, sort_keys=True), encoding="utf-8")
            path = write_evidence(args.evidence_dir, kind="plan", counts=counts, now=moment)
            print(f"PASS: wrote {path}; nothing was deleted")
            return 0
        assert plan is not None
        if plan["counts"] != counts:
            return _refuse("the counts changed since the plan was written; run `plan` again")
        result = apply_purge(
            stores,
            chosen,
            purge_customer=purge_customer,
            kept={name: c["kept"] for name, c in counts.items()},
            batch_size=args.batch_size,
        )
        path = write_evidence(
            args.evidence_dir,
            kind="apply",
            counts=result.counts,
            now=moment,
            failure=result.failure,
        )
    finally:
        stores.close()
    if result.failure is not None:
        print(
            f"FAILED: delete_failed ({result.failure}); the purge stopped; evidence {path}",
            file=sys.stderr,
        )
        return EXIT_FAILED
    if result.stopped:
        print(f"FAILED: an unexpected document stopped the purge; evidence {path}", file=sys.stderr)
        return EXIT_FAILED
    print(f"PASS: wrote {path}")
    return 0


if __name__ == "__main__":
    if isinstance(sys.stdout, io.TextIOWrapper):
        sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
