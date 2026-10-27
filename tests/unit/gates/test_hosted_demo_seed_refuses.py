"""PRP-32 item 5: ``hosted_demo_seed.py`` refuses before any network or client (no network)."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[3]
SCRIPT = REPO / "scripts" / "gates" / "hosted_demo_seed.py"
DEPLOYMENT = "demo-0001"
TENANT = "0f1e2d3c-4b5a-4968-8776-a5b4c3d2e1f0"
OPERATOR_OID = "55555555-5555-4555-8555-555555555555"


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("hosted_demo_seed_under_test", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


gate = _load()


def _registration(tmp_path: Path) -> Path:
    doc = {
        "schema": 1,
        "deployment_id": DEPLOYMENT,
        "cloud": "AzureCloud",
        "cosmos_host": "nsdemo-cosmos.documents.azure.com",
        "eventhubs_host": "nsdemo-ehns.servicebus.windows.net",
        "blob_host": "nsdemoarchive.blob.core.windows.net",
        "key_vault_host": "nsdemo-kv.vault.azure.net",
        "database": "neurosphere",
        "event_hub": "telemetry",
        "archive_container": "ns-archive",
        "pseudonym_secret_uri": "https://nsdemo-kv.vault.azure.net/secrets/pseudonym",
        "workers_object_id": "6c1d2e3f-4a5b-4c6d-8e7f-90a1b2c3d4e5",
        "customer_id": "synthco",
    }
    path = tmp_path / "registration.json"
    path.write_text(json.dumps(doc), encoding="utf-8")
    return path


def _env(**extra: str) -> dict[str, str]:
    env = {
        "NS_ENV": "prod",
        "NS_CLOUD": "commercial",
        "NS_LIVE_APPROVED": "1",
        "NS_SANDBOX_HOSTED_DEPLOYMENT_ID": DEPLOYMENT,
        "NS_AUTH_TENANT_ID": TENANT,
    }
    env.update(extra)
    return env


@pytest.fixture
def no_clients(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fail the test if any credential or client constructor runs."""
    _guard, seed = gate._load_modules()  # pyright: ignore[reportPrivateUsage]

    def boom(*_a: Any, **_k: Any) -> Any:
        raise AssertionError("a credential or client was constructed")

    for name in (
        "new_credential",
        "new_async_credential",
        "new_cosmos",
        "new_sync_cosmos",
        "new_producer",
        "new_archive_container",
    ):
        monkeypatch.setattr(seed, name, boom)
    monkeypatch.setattr(seed.grants, "hosted_pseudonym_env", boom)


def _args(tmp_path: Path) -> list[str]:
    return [
        "--operator-object-id",
        OPERATOR_OID,
        "--registration",
        str(_registration(tmp_path)),
        "--input-dir",
        str(tmp_path / "input"),
        "--evidence-dir",
        str(tmp_path / "evidence"),
    ]


def test_without_approval_exit_2_and_nothing_is_touched(
    tmp_path: Path, no_clients: None, capsys: pytest.CaptureFixture[str]
) -> None:
    env = _env()
    del env["NS_LIVE_APPROVED"]
    assert gate.main(_args(tmp_path), env=env) == 2
    assert "NS_LIVE_APPROVED=1" in capsys.readouterr().err
    assert not (tmp_path / "input").exists()
    assert not (tmp_path / "evidence").exists()


def test_approval_other_than_one_is_refused(tmp_path: Path, no_clients: None) -> None:
    assert gate.main(_args(tmp_path), env=_env(NS_LIVE_APPROVED="true")) == 2


@pytest.mark.parametrize(
    "name",
    [
        "NS_SANDBOX_" + "COSMOS_KEY",
        "NS_COSMOS_" + "KEY",
        "NS_EVENTHUBS_" + "CONNECTION_STRING",
        "NS_SANDBOX_EVENTHUBS_" + "CONNECTION_STRING",
        "NS_BLOB_" + "CONNECTION_STRING",
    ],
)
def test_key_or_connection_string_env_is_refused(
    tmp_path: Path, no_clients: None, name: str, capsys: pytest.CaptureFixture[str]
) -> None:
    value = "not-a-" + "real-value"
    assert gate.main(_args(tmp_path), env=_env(**{name: value})) == 2
    assert value not in capsys.readouterr().err
    assert not (tmp_path / "input").exists()


def test_id_mismatch_and_missing_registration_are_refused(tmp_path: Path, no_clients: None) -> None:
    assert gate.main(_args(tmp_path), env=_env(NS_SANDBOX_HOSTED_DEPLOYMENT_ID="other")) == 2
    args = _args(tmp_path)
    args[args.index("--registration") + 1] = str(tmp_path / "absent.json")
    assert gate.main(args, env=_env()) == 2


def test_the_parser_accepts_no_key_or_connection_string_option() -> None:
    options = {o for a in gate.build_parser()._actions for o in a.option_strings}  # pyright: ignore[reportPrivateUsage]
    assert not {o for o in options if "key" in o or "connection" in o}


def test_seed_input_is_the_synthetic_generator_output(tmp_path: Path) -> None:
    _guard, seed = gate._load_modules()  # pyright: ignore[reportPrivateUsage]
    config = seed.resolve_hosted_config("small", None, _env(), _registration(tmp_path))
    counts = gate.generate_input(seed, config, tmp_path / "input")
    assert gate.GENERATOR_OUTPUT_DIR == REPO / "temp" / "sandbox"
    assert counts["telemetry.ndjson"] > 0 and counts["cost.ndjson"] > 0
    first = json.loads((tmp_path / "input" / "telemetry.ndjson").read_text("utf-8").splitlines()[0])
    assert first["customer_id"] == "synthco"
    assert config.seed == seed.SEED_NUMBER  # deterministic seed


def test_evidence_holds_counts_only(tmp_path: Path) -> None:
    path = gate.write_evidence(
        tmp_path,
        profile="small",
        generated={"telemetry.ndjson": 10},
        summary={"seeded": {"ledger": 4}, "skipped_existing": 1},
    )
    text = path.read_text(encoding="utf-8")
    doc = json.loads(text)
    assert doc["seeded"] == {"ledger": 4} and doc["skipped_existing"] == 1
    for forbidden in ("azure", "http", OPERATOR_OID, TENANT, DEPLOYMENT):
        assert forbidden not in text
