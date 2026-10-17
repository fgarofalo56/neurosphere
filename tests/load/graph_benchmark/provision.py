"""Control-plane provisioning for the live G03 run (Azure CLI, no keys).

The azure-cosmos data-plane SDK cannot create or delete databases/containers with an Entra
token (403, substatus 5300: "cannot be authorized by AAD token in data plane"). The live path
therefore provisions through the Azure CLI (ARM control plane) and benchmarks over the data
plane with Entra. The emulator (key auth) path never uses this module.

`az cosmosdb sql container create` accepts a single ``--partition-key-path`` only (verified
against the local help and parser: a second path is "unrecognized arguments"), so hierarchical
(MultiHash) containers are created with ``az rest`` against the ARM container resource. Never
``az deployment`` (denied by repo settings); always list args, ``shell=False``.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import tempfile
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from .model import PartitionVariant

AZ_TIMEOUT_SECONDS = 600
ARM_API_VERSION = "2024-05-15"
ARM_HOST = "https://management.azure.com"

_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")
_RG_RE = re.compile(r"^[A-Za-z0-9._()-]{1,90}$")
_GUID_RE = re.compile(r"^[0-9a-fA-F]{8}(-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}$")


@dataclass(frozen=True)
class AzResult:
    returncode: int
    stdout: str
    stderr: str


class AzRunner(Protocol):
    def __call__(self, args: Sequence[str]) -> AzResult: ...


class SubprocessAzRunner:
    """The real runner: resolved `az`, list args, no shell (mirrors g01_deploy_smoke)."""

    def __init__(self, az_path: str, timeout: int = AZ_TIMEOUT_SECONDS) -> None:
        self._az = az_path
        self._timeout = timeout

    def __call__(self, args: Sequence[str]) -> AzResult:
        proc = subprocess.run(
            [self._az, *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            stdin=subprocess.DEVNULL,
            timeout=self._timeout,
            check=False,
            shell=False,
        )
        return AzResult(proc.returncode, proc.stdout, proc.stderr)


def resolve_az() -> str | None:
    return shutil.which("az")


class ProvisioningError(RuntimeError):
    pass


class Provisioner(Protocol):
    def create_database(self, name: str) -> None: ...

    def create_container(self, db: str, name: str, variant: PartitionVariant) -> None: ...

    def delete_database(self, name: str) -> None: ...


def valid_account_name(value: str) -> bool:
    return bool(_NAME_RE.fullmatch(value)) and len(value) >= 3


def valid_resource_group(value: str) -> bool:
    return bool(_RG_RE.fullmatch(value))


def valid_subscription(value: str) -> bool:
    return bool(_GUID_RE.fullmatch(value))


class AzCliProvisioner:
    """Creates/deletes SQL databases and containers on a (serverless) Cosmos account."""

    def __init__(
        self,
        account_name: str,
        resource_group: str,
        subscription: str,
        runner: AzRunner,
        *,
        sleep: Callable[[float], None] = time.sleep,
        poll_attempts: int = 30,
        poll_seconds: float = 5.0,
    ) -> None:
        if not valid_account_name(account_name):
            raise ValueError("invalid Cosmos account name")
        if not valid_resource_group(resource_group):
            raise ValueError("invalid resource group")
        if not valid_subscription(subscription):
            raise ValueError("invalid subscription id (expected a GUID)")
        self.account_name = account_name
        self.resource_group = resource_group
        self.subscription = subscription
        self._run = runner
        self._sleep = sleep
        self._poll_attempts = poll_attempts
        self._poll_seconds = poll_seconds

    def _scope(self) -> list[str]:
        return [
            "--subscription",
            self.subscription,
            "--resource-group",
            self.resource_group,
            "--account-name",
            self.account_name,
        ]

    def _exec(self, args: list[str], what: str) -> AzResult:
        res = self._run(args)
        if res.returncode != 0:
            detail = (res.stderr or res.stdout).strip().splitlines()
            raise ProvisioningError(
                f"{what} failed (az exit {res.returncode}): {' | '.join(detail[-3:])[:600]}"
            )
        return res

    def create_database(self, name: str) -> None:
        self._exec(
            ["cosmosdb", "sql", "database", "create", "--name", name, *self._scope()],
            f"create database {name}",
        )

    def delete_database(self, name: str) -> None:
        self._exec(
            ["cosmosdb", "sql", "database", "delete", "--name", name, *self._scope(), "--yes"],
            f"delete database {name}",
        )

    def create_container(self, db: str, name: str, variant: PartitionVariant) -> None:
        if not variant.hierarchical:
            self._exec(
                [
                    "cosmosdb",
                    "sql",
                    "container",
                    "create",
                    "--name",
                    name,
                    "--database-name",
                    db,
                    "--partition-key-path",
                    variant.paths[0],
                    *self._scope(),
                ],
                f"create container {name}",
            )
            return
        self._create_hierarchical(db, name, variant)

    def container_url(self, db: str, name: str) -> str:
        return (
            f"{ARM_HOST}/subscriptions/{self.subscription}/resourceGroups/{self.resource_group}"
            f"/providers/Microsoft.DocumentDB/databaseAccounts/{self.account_name}"
            f"/sqlDatabases/{db}/containers/{name}?api-version={ARM_API_VERSION}"
        )

    def _create_hierarchical(self, db: str, name: str, variant: PartitionVariant) -> None:
        body = {
            "properties": {
                "resource": {
                    "id": name,
                    "partitionKey": {
                        "paths": list(variant.paths),
                        "kind": "MultiHash",
                        "version": 2,
                    },
                },
                "options": {},
            }
        }
        # A body file avoids JSON quoting through az.cmd on Windows.
        with tempfile.TemporaryDirectory(prefix="g03-") as tmp:
            body_file = Path(tmp) / "container.json"
            body_file.write_text(json.dumps(body), encoding="utf-8")
            self._exec(
                [
                    "rest",
                    "--method",
                    "put",
                    "--subscription",
                    self.subscription,
                    "--url",
                    self.container_url(db, name),
                    "--body",
                    f"@{body_file}",
                ],
                f"create hierarchical container {name}",
            )
        self._wait_container(db, name)

    def _wait_container(self, db: str, name: str) -> None:
        """The ARM PUT is asynchronous; poll `container show` until the resource exists."""
        args = [
            "cosmosdb",
            "sql",
            "container",
            "show",
            "--name",
            name,
            "--database-name",
            db,
            *self._scope(),
        ]
        for attempt in range(self._poll_attempts):
            if self._run(args).returncode == 0:
                return
            if attempt + 1 < self._poll_attempts:
                self._sleep(self._poll_seconds)
        raise ProvisioningError(f"container {name} did not become available after creation")


def current_subscription(runner: AzRunner) -> str:
    """`az account show --query id` (the active subscription), or raise."""
    res = runner(["account", "show", "--query", "id", "--output", "tsv"])
    if res.returncode != 0:
        raise ProvisioningError("az account show failed; run `az login` first")
    return res.stdout.strip()
