"""G01 deploy smoke: approval gate, preconditions, flow, teardown guard and evidence hygiene.

Every test drives the script through a fake `az` runner; no subprocess and no network.
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "gates" / "g01_deploy_smoke.py"
SUB = "11111111-2222-3333-4444-555555555555"
RG = "rg-ns-g01-test"
BASE = f"/subscriptions/{SUB}/resourceGroups/{RG}/providers"
KV_ID = f"{BASE}/Microsoft.KeyVault/vaults/nskv1"
APIM_ID = f"{BASE}/Microsoft.ApiManagement/service/nsapim1"
COSMOS_ID = f"{BASE}/Microsoft.DocumentDB/databaseAccounts/nscosmos1"
REUSED_APIM = (
    "/subscriptions/99999999-0000-0000-0000-000000000000/resourceGroups/rg-shared/providers/"
    "Microsoft.ApiManagement/service/shared-apim"
)
FAKE_JWT = "eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJ4In0.c2lnbmF0dXJl"
FAKE_KEY = "AccountKey=" + "QUJDREVGR0hJSktMTU5PUFFSU1RVVldYWVowMTIzNDU2Nzg5YWJjZGVm=="


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("g01_under_test", SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["g01_under_test"] = mod
    spec.loader.exec_module(mod)
    return mod


def _res(rid: str, rtype: str, name: str, state: str = "Succeeded") -> dict[str, Any]:
    return {
        "id": rid,
        "type": rtype,
        "name": name,
        "location": "eastus2",
        "provisioningState": state,
        # Unexpected fields that must never reach the evidence file.
        "accessToken": FAKE_JWT,
        "properties": {"primaryKey": FAKE_KEY},
    }


class FakeAz:
    """Canned `az` responses keyed on the leading arguments; records every call."""

    def __init__(self, *, with_apim: bool = True) -> None:
        self.calls: list[list[str]] = []
        self.cloud = "AzureCloud"
        self.account = SUB
        self.group_exists: Any = False
        self.deploy_rc = 0
        self.deploy_state = "Succeeded"
        self.kv_purge: tuple[int, str] = (0, "")
        self.kv_purge_protected: bool | None = None
        self.resources = [
            _res(COSMOS_ID, "Microsoft.DocumentDB/databaseAccounts", "nscosmos1"),
            _res(KV_ID, "Microsoft.KeyVault/vaults", "nskv1"),
        ]
        if with_apim:
            self.resources.append(_res(APIM_ID, "Microsoft.ApiManagement/service", "nsapim1"))
        self.extra_after_deploy: list[dict[str, Any]] = []
        self._deployed = False

    def names(self) -> list[str]:
        return [" ".join(c[:3]) for c in self.calls]

    def __call__(self, args: Sequence[str]) -> Any:
        from collections import namedtuple

        r = namedtuple("R", "rc stdout stderr")
        a = list(args)
        self.calls.append(a)
        head = " ".join(a[:2])
        if head == "cloud show":
            return r(0, json.dumps(self.cloud), "")
        if head == "account show":
            return r(0, json.dumps(self.account), "")
        if head == "group exists":
            return r(0, json.dumps(self.group_exists), "")
        if head == "group create":
            return r(0, json.dumps({"properties": {"provisioningState": "Succeeded"}}), "")
        if head == "bicep build-params":
            params = {"namePrefix": {"value": "nsphere"}, "location": {"value": "eastus2"}}
            return r(0, json.dumps({"parameters": params}), "")
        if a[:3] == ["deployment", "group", "what-if"]:
            changes = [{"changeType": "Create", "resourceId": x["id"]} for x in self.resources]
            changes[0]["after"] = {"properties": {"primaryKey": FAKE_KEY}}  # type: ignore[assignment]
            return r(0, json.dumps({"status": "Succeeded", "changes": changes}), "")
        if a[:3] == ["deployment", "group", "create"]:
            if self.deploy_rc:
                return r(self.deploy_rc, "", "Deployment failed: quota exceeded")
            self._deployed = True
            body = {
                "properties": {
                    "provisioningState": self.deploy_state,
                    "outputs": {
                        "keyVaultId": {"type": "String", "value": KV_ID},
                        "cloudName": {"type": "String", "value": "AzureCloud"},
                        "leaked": {"type": "String", "value": FAKE_JWT},
                    },
                }
            }
            return r(0, json.dumps(body), "")
        if head == "resource list":
            live = list(self.resources) if self._deployed else []
            if self._deployed and self.calls.count(a) > 1:
                live += self.extra_after_deploy
            return r(0, json.dumps(live), "")
        if head == "group delete":
            return r(0, "", "")
        if a[:2] == ["keyvault", "purge"]:
            return r(self.kv_purge[0], "", self.kv_purge[1])
        if a[:2] == ["keyvault", "show-deleted"]:
            if self.kv_purge_protected is None:
                return r(1, "", "not found")
            props = {"purgeProtectionEnabled": self.kv_purge_protected}
            return r(0, json.dumps({"properties": props}), "")
        if a[:3] == ["apim", "deletedservice", "purge"]:
            return r(0, "", "")
        return r(1, "", f"unexpected call {a}")


def _argv(tmp: Path, *extra: str, apim: bool = True) -> list[str]:
    base = ["--subscription", SUB, "--resource-group", RG, "--evidence-dir", str(tmp / "ev")]
    if apim and "--reuse-apim" not in extra:
        base += ["--apim-publisher-email", "ops@example.invalid", "--apim-publisher-name", "Ops"]
    return [*base, *extra]


def _run(fake: FakeAz, tmp: Path, *extra: str, apim: bool = True) -> int:
    mod = _load()
    return mod.main(_argv(tmp, *extra, apim=apim), runner=fake, work_dir=tmp / "work")


def _evidence(tmp: Path) -> tuple[Path, dict[str, Any]]:
    files = sorted((tmp / "ev").glob("*-commercial-deploy-smoke.json"))
    assert len(files) == 1
    return files[0], json.loads(files[0].read_text(encoding="utf-8"))


@pytest.fixture(autouse=True)
def _approved(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NS_LIVE_APPROVED", "1")


@pytest.mark.parametrize("value", [None, "0", "true", "", "yes"])
def test_refuses_without_approval_and_runs_nothing(
    value: str | None,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    if value is None:
        monkeypatch.delenv("NS_LIVE_APPROVED", raising=False)
    else:
        monkeypatch.setenv("NS_LIVE_APPROVED", value)
    fake = FakeAz()
    rc = _load().main([], runner=fake, work_dir=tmp_path)  # no args: refusal comes first
    err = capsys.readouterr().err
    assert rc != 0
    assert "REFUSED" in err and "NS_LIVE_APPROVED" in err and "billable" in err
    assert fake.calls == []
    assert not (tmp_path / "ev").exists()


def test_subprocess_refuses_end_to_end() -> None:
    env = {k: v for k, v in os.environ.items() if k != "NS_LIVE_APPROVED"}
    proc = subprocess.run(
        [sys.executable, str(SCRIPT)], env=env, capture_output=True, text=True, timeout=60
    )
    assert proc.returncode != 0
    assert "REFUSED" in proc.stderr


def test_refuses_before_any_az_call_when_register_is_not_importable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # A plain `python` run once created the RG and then crashed in teardown on this import.
    monkeypatch.setitem(sys.modules, "neurosphere_core.deploy.register", None)
    fake = FakeAz()
    assert _run(fake, tmp_path) == 2
    assert "uv run" in capsys.readouterr().err
    assert fake.calls == []
    assert not (tmp_path / "ev").exists()


@pytest.mark.parametrize("loc", ["usgovvirginia", "usdodeast", "USGovArizona"])
def test_refuses_government_location(loc: str, tmp_path: Path) -> None:
    fake = FakeAz()
    assert _run(fake, tmp_path, "--location", loc) != 0
    assert fake.calls == []


def test_refuses_when_resource_group_exists(tmp_path: Path) -> None:
    fake = FakeAz()
    fake.group_exists = True
    assert _run(fake, tmp_path) != 0
    assert not any(c[:2] in (["group", "create"], ["group", "delete"]) for c in fake.calls)
    assert not (tmp_path / "ev").exists()


@pytest.mark.parametrize(
    ("cloud", "account"),
    [("AzureUSGovernment", SUB), ("AzureCloud", "00000000-0000-0000-0000-000000000000")],
)
def test_refuses_wrong_cloud_or_subscription(cloud: str, account: str, tmp_path: Path) -> None:
    fake = FakeAz()
    fake.cloud, fake.account = cloud, account
    assert _run(fake, tmp_path) != 0
    assert not any(c[:2] == ["group", "create"] for c in fake.calls)


def test_requires_publisher_when_creating_apim(tmp_path: Path) -> None:
    fake = FakeAz()
    assert _run(fake, tmp_path, apim=False) != 0
    assert fake.calls == []


def test_happy_path_evidence_and_teardown_order(tmp_path: Path) -> None:
    fake = FakeAz()
    assert _run(fake, tmp_path) == 0
    path, ev = _evidence(tmp_path)
    for key in (
        "script_version",
        "started_utc",
        "finished_utc",
        "cloud",
        "subscription_id",
        "resource_group",
        "location",
        "what_if",
        "resources_created",
        "health",
        "teardown",
        "gate",
        "result",
    ):
        assert key in ev
    assert ev["result"] == "PASS" and ev["gate"] == "G01" and ev["cloud"] == "commercial"
    token = _load().subscription_token(SUB)

    def red(rid: str) -> str:
        return rid.replace(SUB, token)

    assert ev["subscription_id"] == token
    assert ev["what_if"]["counts_by_change_type"] == {"Create": 3}
    assert ev["deployment"]["output_resource_ids"] == {"keyVaultId": red(KV_ID)}
    assert {r["id"] for r in ev["resources_created"]} == {red(COSMOS_ID), red(KV_ID), red(APIM_ID)}
    assert ev["health"]["ok"] is True
    assert path.with_suffix(".md").exists()

    kinds = [c[:2] if c[0] != "apim" else c[:3] for c in fake.calls]
    order = [
        kinds.index(["group", "delete"]),
        kinds.index(["keyvault", "purge"]),
        kinds.index(["apim", "deletedservice", "purge"]),
    ]
    assert order == sorted(order)
    assert any(c[:2] == ["group", "create"] and "neurosphere:gate=G01" in c for c in fake.calls)


def test_keep_skips_teardown(tmp_path: Path) -> None:
    fake = FakeAz()
    assert _run(fake, tmp_path, "--keep") == 0
    assert not any(c[:2] == ["group", "delete"] for c in fake.calls)
    _, ev = _evidence(tmp_path)
    assert ev["teardown"]["performed"] is False and ev["kept"] is True


def test_no_credential_value_reaches_evidence(tmp_path: Path) -> None:
    fake = FakeAz()
    assert _run(fake, tmp_path) == 0
    path, _ = _evidence(tmp_path)
    for text in (
        path.read_text(encoding="utf-8"),
        path.with_suffix(".md").read_text(encoding="utf-8"),
    ):
        assert "eyJ" not in text
        assert "AccountKey" not in text
        assert "QUJDREVG" not in text
        assert "ops@example.invalid" not in text


def test_scrubber_fails_the_run_on_secret_in_whitelisted_field(tmp_path: Path) -> None:
    fake = FakeAz()
    fake.resources[0]["id"] = KV_ID + "/" + FAKE_KEY  # whitelisted field carrying a secret
    assert _run(fake, tmp_path) != 0
    path, ev = _evidence(tmp_path)
    assert ev["result"] == "FAIL"
    assert "QUJDREVG" not in path.read_text(encoding="utf-8")


@pytest.mark.parametrize(
    "bad",
    [FAKE_JWT, FAKE_KEY, "SharedAccessKey=abc", "-----BEGIN PRIVATE KEY-----", "x" * 45 + "=="],
)
def test_scrubber_patterns(bad: str) -> None:
    mod = _load()
    with pytest.raises(mod.ScrubError):
        mod.scrub({"a": [bad]})
    with pytest.raises(mod.ScrubError):
        mod.scrub({"primaryKey": "x"})
    mod.scrub({"id": KV_ID, "state": "Succeeded"})


def test_teardown_refuses_foreign_resource(tmp_path: Path) -> None:
    fake = FakeAz()
    fake.extra_after_deploy = [
        _res(f"{BASE}/Microsoft.Storage/storageAccounts/foreign1", "Microsoft.Storage/x", "f1")
    ]
    assert _run(fake, tmp_path) != 0
    assert not any(c[:2] == ["group", "delete"] for c in fake.calls)
    assert not any(c[0] in ("keyvault", "apim") for c in fake.calls)
    _, ev = _evidence(tmp_path)
    assert ev["result"] == "FAIL"


def test_reused_apim_is_never_deleted_or_purged(tmp_path: Path) -> None:
    fake = FakeAz(with_apim=False)
    assert _run(fake, tmp_path, "--reuse-apim", REUSED_APIM) == 0
    flat = [" ".join(c) for c in fake.calls]
    assert not any(c[:3] == ["apim", "deletedservice", "purge"] for c in fake.calls)
    assert not any("deletedservice" in line for line in flat)
    deletes = [c for c in fake.calls if c[:2] == ["group", "delete"]]
    assert len(deletes) == 1 and RG in deletes[0]
    assert not any("shared-apim" in line for line in flat if "group delete" in line)
    build = next(c for c in fake.calls if c[:2] == ["bicep", "build-params"])
    assert build  # params built offline
    deploy = next(c for c in fake.calls if c[:3] == ["deployment", "group", "create"])
    assert deploy[deploy.index("--parameters") + 1].startswith("@")


def test_reused_apim_seen_live_in_group_is_refused(tmp_path: Path) -> None:
    fake = FakeAz(with_apim=False)
    fake.resources.append(_res(REUSED_APIM, "Microsoft.ApiManagement/service", "shared-apim"))
    # Even if listed live, the reused APIM must not be treated as created or deleted with the RG.
    assert _run(fake, tmp_path, "--reuse-apim", REUSED_APIM) != 0
    assert not any(c[:2] == ["group", "delete"] for c in fake.calls)


def test_failure_mid_deploy_still_tears_down_and_records_fail(tmp_path: Path) -> None:
    fake = FakeAz()
    fake.deploy_rc = 1
    assert _run(fake, tmp_path) != 0
    assert any(c[:2] == ["group", "delete"] for c in fake.calls)
    _, ev = _evidence(tmp_path)
    assert ev["result"] == "FAIL"
    assert ev["teardown"]["performed"] is True
    assert ev["errors"]


def test_unhealthy_resource_fails_but_still_tears_down(tmp_path: Path) -> None:
    fake = FakeAz()
    fake.resources[0]["provisioningState"] = "Failed"
    assert _run(fake, tmp_path) != 0
    assert any(c[:2] == ["group", "delete"] for c in fake.calls)
    _, ev = _evidence(tmp_path)
    assert ev["result"] == "FAIL" and ev["health"]["ok"] is False


def test_keyvault_purge_protection_is_recorded_not_hidden(tmp_path: Path) -> None:
    fake = FakeAz()
    fake.kv_purge = (1, "Vault is protected by purge protection")
    assert _run(fake, tmp_path) == 0
    _, ev = _evidence(tmp_path)
    assert "blocked_by_purge_protection" in ev["teardown"]["purge"].values()


def test_keyvault_method_not_allowed_counts_as_purge_protection_when_vault_says_so(
    tmp_path: Path,
) -> None:
    # Real Azure wording (2026-10-17) never mentions purge protection.
    fake = FakeAz()
    fake.kv_purge = (1, "(MethodNotAllowed) Operation 'DeletedVaultPurge' is not allowed.")
    fake.kv_purge_protected = True
    assert _run(fake, tmp_path) == 0
    _, ev = _evidence(tmp_path)
    assert ev["result"] == "PASS"
    assert "blocked_by_purge_protection" in ev["teardown"]["purge"].values()


def test_evidence_never_contains_a_subscription_id(tmp_path: Path) -> None:
    # The repository is public: subscription ids are tokenised in the JSON and the Markdown.
    fake = FakeAz()
    assert _run(fake, tmp_path) == 0
    path, ev = _evidence(tmp_path)
    token = _load().subscription_token(SUB)
    for text in (path.read_text(encoding="utf-8"), path.with_suffix(".md").read_text("utf-8")):
        assert SUB.lower() not in text.lower()
        assert token in text
    assert ev["subscription_id"] == token
    assert any("subscription ids replaced" in note for note in ev["redactions"])


def test_keyvault_purge_failure_without_protection_still_fails(tmp_path: Path) -> None:
    fake = FakeAz()
    fake.kv_purge = (1, "(MethodNotAllowed) Operation 'DeletedVaultPurge' is not allowed.")
    fake.kv_purge_protected = False
    assert _run(fake, tmp_path) == 1
    _, ev = _evidence(tmp_path)
    assert ev["result"] == "FAIL"
    assert "failed" in ev["teardown"]["purge"].values()
