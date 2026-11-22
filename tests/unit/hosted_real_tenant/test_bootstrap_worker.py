"""bootstrap-worker: viewer for the workers principal on named domains, hosted guards first."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "gates" / "hosted_real_tenant.py"
TENANT = "00000000-0000-0000-0000-0000000000cc"
WORKERS = "00000000-0000-0000-0000-0000000000aa"
DOMAIN = "commercial:fakecust:domain:fake-domain:alpha"
ENV = {
    "NS_LIVE_APPROVED": "1",
    "NS_ENV": "prod",
    "NS_SANDBOX_HOSTED_DEPLOYMENT_ID": "fake-deploy",
    "NS_AUTH_TENANT_ID": TENANT,
}


def load() -> ModuleType:
    name = "hosted_real_tenant_under_test"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def registration(tmp_path: Path, **extra: object) -> Path:
    doc = {
        "schema": 1,
        "deployment_id": "fake-deploy",
        "cloud": "AzureCloud",
        "workers_object_id": WORKERS,
        "customer_id": "fakecust",
        "cosmos_host": "fake.documents.azure.com",
        **extra,
    }
    path = tmp_path / "registration.json"
    path.write_text(json.dumps(doc), encoding="utf-8")
    return path


class Recorder:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def __call__(self, **kwargs: Any) -> str:
        self.calls.append(kwargs)
        return "created"


def run(tmp_path: Path, env: dict[str, str], *extra: str, **reg: object) -> tuple[int, Recorder]:
    rec = Recorder()
    argv = ["bootstrap-worker", "--registration", str(registration(tmp_path, **reg)), *extra]
    if "--domain-ids" not in extra:
        argv += ["--domain-ids", DOMAIN]
    return load().main(argv, env=env, grant_runner=rec), rec


def test_grants_viewer_to_the_registered_workers_principal(tmp_path: Path) -> None:
    code, rec = run(tmp_path, ENV)
    assert code == 0
    (call,) = rec.calls
    assert call["worker_object_id"] == WORKERS
    assert call["customer"] == "fakecust"
    assert call["domain_ids"] == [DOMAIN]
    assert call["tenant"] == TENANT


def test_refuses_without_live_approval(tmp_path: Path) -> None:
    code, rec = run(tmp_path, {k: v for k, v in ENV.items() if k != "NS_LIVE_APPROVED"})
    assert code == 2 and rec.calls == []


def test_refuses_government(tmp_path: Path) -> None:
    code, rec = run(tmp_path, ENV, cloud="AzureUSGovernment")
    assert code == 2 and rec.calls == []
    code, rec = run(tmp_path, {**ENV, "NS_CLOUD": "government"})
    assert code == 2 and rec.calls == []


def test_refuses_key_or_connection_string_env(tmp_path: Path) -> None:
    code, rec = run(tmp_path, {**ENV, "NS_COSMOS_KEY": "x"})
    assert code == 2 and rec.calls == []


def test_refuses_unregistered_deployment_and_local_env(tmp_path: Path) -> None:
    code, rec = run(tmp_path, {**ENV, "NS_SANDBOX_HOSTED_DEPLOYMENT_ID": "other"})
    assert code == 2 and rec.calls == []
    code, rec = run(tmp_path, {**ENV, "NS_ENV": "local"})
    assert code == 2 and rec.calls == []


def test_refuses_domain_of_another_customer_or_cloud(tmp_path: Path) -> None:
    for bad in (
        "commercial:othercust:domain:fake-domain:alpha",
        "government:fakecust:domain:fake-domain:alpha",
        "not-a-domain",
    ):
        code, rec = run(tmp_path, ENV, "--domain-ids", bad)
        assert code == 2 and rec.calls == []


def test_refuses_customer_override_that_differs(tmp_path: Path) -> None:
    code, rec = run(tmp_path, ENV, "--customer-id", "othercust")
    assert code == 2 and rec.calls == []


def test_refuses_bad_tenant(tmp_path: Path) -> None:
    code, rec = run(tmp_path, {**ENV, "NS_AUTH_TENANT_ID": "not-a-guid"})
    assert code == 2 and rec.calls == []
