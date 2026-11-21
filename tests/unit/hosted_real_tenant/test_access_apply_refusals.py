"""access-apply: approvals, refusals, outcomes and privacy of the evidence (PRP-139 item 6)."""

from __future__ import annotations

import importlib.util
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from types import ModuleType

import pytest

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "gates" / "hosted_real_tenant.py"
SUB = "00000000-0000-0000-0000-000000000001"
WORKERS = "00000000-0000-0000-0000-0000000000aa"
API = "00000000-0000-0000-0000-0000000000bb"
RG = f"/subscriptions/{SUB}/resourceGroups/rg-fake/providers"
FOUNDRY = f"{RG}/Microsoft.CognitiveServices/accounts/fake-account"
STORAGE = f"{RG}/Microsoft.Storage/storageAccounts/fakestorage"
APIM = f"{RG}/Microsoft.ApiManagement/service/fake-apim"
APPROVED = {"NS_LIVE_APPROVED": "1"}


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


class FakeAz:
    def __init__(self, *, existing: bool = False, cloud: str = "AzureCloud", create_rc: int = 0):
        self.calls: list[list[str]] = []
        self.existing = existing
        self.cloud = cloud
        self.create_rc = create_rc

    def __call__(self, args: Sequence[str]) -> object:
        mod = load()
        argv = list(args)
        self.calls.append(argv)
        if argv[:2] == ["cloud", "show"]:
            return mod.AzResult(0, self.cloud + "\n")
        if argv[:3] == ["role", "assignment", "list"]:
            return mod.AzResult(0, json.dumps([{"id": "x"}] if self.existing else []))
        if argv[:3] == ["role", "assignment", "create"]:
            return mod.AzResult(self.create_rc, "", "AuthorizationFailed" if self.create_rc else "")
        raise AssertionError(f"unexpected az call {argv}")

    def writes(self) -> list[list[str]]:
        return [c for c in self.calls if c[:3] == ["role", "assignment", "create"]]


def make_plan(tmp_path: Path) -> tuple[Path, Path, str, list[str]]:
    mod = load()
    reg = tmp_path / "registration.json"
    reg.write_text(
        json.dumps(
            {
                "schema": 1,
                "deployment_id": "fake-deploy",
                "cloud": "AzureCloud",
                "workers_object_id": WORKERS,
            }
        ),
        encoding="utf-8",
    )
    plan = tmp_path / "plan.json"
    code = mod.main(
        [
            "access-plan",
            "--registration",
            str(reg),
            "--plan-file",
            str(plan),
            "--api-principal-id",
            API,
            "--foundry-account-ids",
            FOUNDRY,
            "--apim-service-ids",
            APIM,
            "--billing-export-storage-account-id",
            STORAGE,
        ],
        env={},
    )
    assert code == 0
    doc = json.loads(plan.read_text(encoding="utf-8"))
    tokens = [r["token"] for r in doc["rows"] if r["verified"]]
    assert len(tokens) == 3
    return reg, plan, doc["plan_hash"], tokens


def apply_args(reg: Path, plan: Path, digest: str, tokens: Sequence[str], ev: Path) -> list[str]:
    args = [
        "access-apply",
        "--registration",
        str(reg),
        "--plan-file",
        str(plan),
        "--approve-plan",
        digest,
        "--evidence-dir",
        str(ev),
    ]
    for tok in tokens:
        args += ["--approve-assignment", tok]
    return args


def test_apply_needs_live_approval(tmp_path: Path) -> None:
    reg, plan, digest, tokens = make_plan(tmp_path)
    az = FakeAz()
    code = load().main(apply_args(reg, plan, digest, tokens, tmp_path / "ev"), env={}, az_runner=az)
    assert code == 2
    assert az.calls == []


def test_apply_refuses_wrong_plan_hash(tmp_path: Path) -> None:
    reg, plan, _digest, tokens = make_plan(tmp_path)
    az = FakeAz()
    args = apply_args(reg, plan, "0" * 16, tokens, tmp_path / "ev")
    assert load().main(args, env=APPROVED, az_runner=az) == 2
    assert az.calls == []


def test_apply_refuses_token_not_in_plan(tmp_path: Path) -> None:
    reg, plan, digest, tokens = make_plan(tmp_path)
    az = FakeAz()
    args = apply_args(reg, plan, digest, [*tokens, "deadbeef0000"], tmp_path / "ev")
    assert load().main(args, env=APPROVED, az_runner=az) == 2
    assert az.calls == []


def test_apply_refuses_when_a_row_has_no_token(tmp_path: Path) -> None:
    reg, plan, digest, tokens = make_plan(tmp_path)
    az = FakeAz()
    args = apply_args(reg, plan, digest, tokens[:-1], tmp_path / "ev")
    assert load().main(args, env=APPROVED, az_runner=az) == 2
    assert az.calls == []


def test_apply_refuses_edited_plan_file(tmp_path: Path) -> None:
    reg, plan, digest, tokens = make_plan(tmp_path)
    doc = json.loads(plan.read_text(encoding="utf-8"))
    doc["rows"][0]["scope"] = f"/subscriptions/{SUB}"
    plan.write_text(json.dumps(doc), encoding="utf-8")
    az = FakeAz()
    args = apply_args(reg, plan, digest, tokens, tmp_path / "ev")
    assert load().main(args, env=APPROVED, az_runner=az) == 2
    assert az.calls == []


def test_apply_refuses_wider_scope_even_with_a_consistent_hash(tmp_path: Path) -> None:
    mod = load()
    reg, plan, _digest, _tokens = make_plan(tmp_path)
    doc = json.loads(plan.read_text(encoding="utf-8"))
    for row in doc["rows"]:
        if row["source"] == "foundry":
            row["scope"] = f"/subscriptions/{SUB}/resourceGroups/rg-fake"
    doc["plan_hash"] = mod.plan_hash(doc["rows"])
    plan.write_text(json.dumps(doc), encoding="utf-8")
    az = FakeAz()
    tokens = [r["token"] for r in doc["rows"] if r["verified"]]
    args = apply_args(reg, plan, doc["plan_hash"], tokens, tmp_path / "ev")
    assert mod.main(args, env=APPROVED, az_runner=az) == 2
    assert az.calls == []


def test_apply_refuses_government_and_wrong_az_cloud(tmp_path: Path) -> None:
    mod = load()
    reg, plan, digest, tokens = make_plan(tmp_path)
    args = apply_args(reg, plan, digest, tokens, tmp_path / "ev")
    gov = FakeAz()
    env = {**APPROVED, "NS_CLOUD": "government"}
    assert mod.main(args, env=env, az_runner=gov) == 2
    assert gov.calls == []
    wrong = FakeAz(cloud="AzureUSGovernment")
    assert mod.main(args, env=APPROVED, az_runner=wrong) == 2
    assert wrong.writes() == []


def test_apply_writes_only_role_assignments_and_records_outcomes(tmp_path: Path) -> None:
    reg, plan, digest, tokens = make_plan(tmp_path)
    az = FakeAz()
    ev = tmp_path / "ev"
    code = load().main(
        apply_args(reg, plan, digest, tokens, ev), env=APPROVED, az_runner=az, today="2026-11-21"
    )
    assert code == 0
    assert len(az.writes()) == 3
    for call in az.calls:
        assert call[:2] in (["cloud", "show"], ["role", "assignment"])
        assert call[:3] != ["role", "assignment", "delete"]
    for call in az.writes():
        scope = call[call.index("--scope") + 1]
        assert scope in (FOUNDRY, STORAGE, APIM)
    evidence = json.loads((ev / "2026-11-21-access.json").read_text(encoding="utf-8"))
    assert evidence["counts"] == {"applied": 3, "already_present": 0, "skipped": 1, "failed": 0}
    skipped = [r for r in evidence["rows"] if r["outcome"] == "skipped"]
    assert skipped[0]["reason"] == "unverified_role"


def test_apply_reports_already_present_and_never_creates(tmp_path: Path) -> None:
    reg, plan, digest, tokens = make_plan(tmp_path)
    az = FakeAz(existing=True)
    ev = tmp_path / "ev"
    code = load().main(
        apply_args(reg, plan, digest, tokens, ev), env=APPROVED, az_runner=az, today="2026-11-21"
    )
    assert code == 0
    assert az.writes() == []
    counts = json.loads((ev / "2026-11-21-access.json").read_text(encoding="utf-8"))["counts"]
    assert counts["already_present"] == 3


def test_apply_failure_is_exit_1_with_a_reason_code(tmp_path: Path) -> None:
    reg, plan, digest, tokens = make_plan(tmp_path)
    az = FakeAz(create_rc=1)
    ev = tmp_path / "ev"
    code = load().main(
        apply_args(reg, plan, digest, tokens, ev), env=APPROVED, az_runner=az, today="2026-11-21"
    )
    assert code == 1
    rows = json.loads((ev / "2026-11-21-access.json").read_text(encoding="utf-8"))["rows"]
    assert {r["reason"] for r in rows if r["outcome"] == "failed"} == {"authorization_failed"}


def test_unverified_row_cannot_be_applied_even_if_its_token_is_forged(tmp_path: Path) -> None:
    mod = load()
    reg, plan, _digest, tokens = make_plan(tmp_path)
    doc = json.loads(plan.read_text(encoding="utf-8"))
    forged = "f" * 12
    for row in doc["rows"]:
        if not row["verified"]:
            row["token"] = forged
    doc["plan_hash"] = mod.plan_hash(doc["rows"])
    plan.write_text(json.dumps(doc), encoding="utf-8")
    az = FakeAz()
    args = apply_args(reg, plan, doc["plan_hash"], [*tokens, forged], tmp_path / "ev")
    assert mod.main(args, env=APPROVED, az_runner=az) == 2
    assert az.writes() == []


def test_evidence_holds_no_identifier(tmp_path: Path) -> None:
    reg, plan, digest, tokens = make_plan(tmp_path)
    ev = tmp_path / "ev"
    load().main(
        apply_args(reg, plan, digest, tokens, ev),
        env=APPROVED,
        az_runner=FakeAz(),
        today="2026-11-21",
    )
    text = (ev / "2026-11-21-access.json").read_text(encoding="utf-8").lower()
    for forbidden in (
        SUB,
        WORKERS,
        API,
        "/subscriptions",
        "fake-account",
        "fakestorage",
        "fake-apim",
    ):
        assert forbidden.lower() not in text
    assert "subscription_hash" in text


@pytest.mark.parametrize("scope_kind", ["child", "wrong_type"])
def test_parse_resource_id_refuses_child_and_wrong_type(scope_kind: str) -> None:
    mod = load()
    scope = {
        "child": f"{FOUNDRY}/projects/p1",
        "wrong_type": STORAGE,
    }[scope_kind]
    with pytest.raises(mod.RefusedError):
        mod.parse_resource_id(scope, "microsoft.cognitiveservices/accounts")
