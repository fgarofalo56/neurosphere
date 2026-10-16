"""Uninstall dry-run against a register held in the Cosmos emulator (and a JSON export).

Emulator limits (PRP-05 C4): no auth or RU enforcement, so this proves the store round trip and
the script's classification, not RBAC. Real removal is live-gated and is not run here.
"""

from __future__ import annotations

import base64
import json
import os
import subprocess
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from azure.cosmos import PartitionKey
from neurosphere_core.clients import ClientLifetime, create_cosmos_client
from neurosphere_core.cloud import Settings
from neurosphere_core.deploy.register import Ownership, RegisterExport, ResourceRow
from neurosphere_core.deploy.register.cosmos_store import PARTITION_KEY_PATH, CosmosRegisterStore
from neurosphere_core.errors import ForbiddenError

pytestmark = pytest.mark.integration

SCRIPT = Path(__file__).resolve().parents[3] / "infra" / "scripts" / "uninstall.py"
RG = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-ns"
NOW = datetime(2026, 10, 16, tzinfo=UTC)


def _rid(name: str) -> str:
    return f"{RG}/providers/Microsoft.Test/things/{name}"


def _rows(dep: str) -> list[ResourceRow]:
    common: dict[str, Any] = {
        "deployment_id": dep,
        "service": "svc",
        "owner": "principal:abc123",
        "creating_plan_id": "plan-1",
        "recorded_at": NOW,
    }
    return [
        ResourceRow(
            **common,
            resource_id=_rid("app"),
            ownership=Ownership.CREATED,
            created_by="neurosphere",
        ),
        ResourceRow(
            **common,
            resource_id=_rid("db"),
            ownership=Ownership.CREATED,
            created_by="neurosphere",
            dependents=(_rid("app"),),
        ),
        ResourceRow(
            **common,
            resource_id=_rid("kv-reused"),
            ownership=Ownership.REUSED,
            consent_reference="consent-1",
        ),
        ResourceRow(
            **common,
            resource_id=_rid("hub-shared"),
            ownership=Ownership.SHARED,
            consent_reference="consent-1",
        ),
        ResourceRow(
            **common,
            resource_id=_rid("log"),
            ownership=Ownership.CREATED,
            created_by="neurosphere",
            dependents=(_rid("foreign-consumer"),),
        ),
    ]


def _run(*args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    full_env = {k: v for k, v in os.environ.items() if k != "NS_LIVE_APPROVED"}
    full_env.update(env or {})
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True,
        text=True,
        env=full_env,
        timeout=120,
        check=False,
    )


def _check_report(report: dict[str, Any]) -> None:
    by_id = {e["resource_id"]: e for e in report["entries"]}
    assert report["dry_run"] is True
    assert by_id[_rid("kv-reused")]["action"] == "untouched"
    assert by_id[_rid("hub-shared")]["action"] == "untouched"
    assert by_id[_rid("log")]["action"] == "untouched"  # foreign dependent
    assert by_id[_rid("log")]["reason"]
    assert report["removable"] == [_rid("app"), _rid("db")]  # dependents first
    assert len(by_id) == 5


def test_dry_run_from_json_export(tmp_path: Path) -> None:
    dep = "dep-json"
    export = tmp_path / "register.json"
    export.write_text(
        RegisterExport(deployment_id=dep, rows=tuple(_rows(dep))).model_dump_json(),
        encoding="utf-8",
    )
    out = tmp_path / "report.json"
    result = _run("--export", str(export), "--dry-run", "--report", str(out))
    assert result.returncode == 0, result.stderr
    _check_report(json.loads(out.read_text(encoding="utf-8")))


async def test_dry_run_from_cosmos_emulator() -> None:
    dep = f"dep-{uuid.uuid4().hex[:8]}"
    env = {
        "NS_ENV": "local",
        "NS_COSMOS_ENDPOINT": "http://localhost:8081",
        "NS_COSMOS_KEY": base64.b64encode(b"emulator-ignores-this").decode(),
    }
    os.environ.update(env)
    settings = Settings(env="local")
    async with ClientLifetime() as lt:
        client = create_cosmos_client(settings, lifetime=lt)
        db = await client.create_database_if_not_exists("ns_register_test")
        await db.create_container_if_not_exists(
            "register", partition_key=PartitionKey(path=PARTITION_KEY_PATH)
        )
        store = CosmosRegisterStore.from_client(
            client, database="ns_register_test", container="register"
        )
        for row in _rows(dep):
            await store.put_row(row)
        # Ownership downgrade is refused by the Cosmos store too.
        with pytest.raises(ForbiddenError):
            await store.put_row(_rows(dep)[0].model_copy(update={"resource_id": _rid("kv-reused")}))
        assert len(await store.list_rows(dep)) == 5

    result = await _run_async(
        "--cosmos-database", "ns_register_test", "--cosmos-container", "register",
        "--deployment-id", dep, "--dry-run", env=env,
    )  # fmt: skip
    assert result.returncode == 0, result.stderr
    _check_report(json.loads(result.stdout))


async def _run_async(*args: str, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    import asyncio

    return await asyncio.to_thread(_run, *args, env=env)


def test_real_removal_refused_without_approval_or_confirm(tmp_path: Path) -> None:
    dep = "dep-refuse"
    export = tmp_path / "register.json"
    export.write_text(
        RegisterExport(deployment_id=dep, rows=tuple(_rows(dep))).model_dump_json(),
        encoding="utf-8",
    )
    no_approval = _run("--export", str(export), "--confirm", dep)
    assert no_approval.returncode == 3
    assert "NS_LIVE_APPROVED" in no_approval.stderr

    wrong_confirm = _run(
        "--export", str(export), "--confirm", "other", env={"NS_LIVE_APPROVED": "1"}
    )
    assert wrong_confirm.returncode == 3
    assert "--confirm" in wrong_confirm.stderr

    missing_confirm = _run("--export", str(export), env={"NS_LIVE_APPROVED": "1"})
    assert missing_confirm.returncode == 3
