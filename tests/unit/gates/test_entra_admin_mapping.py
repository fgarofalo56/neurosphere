"""PRP-138 item 8: entra_admin_mapping.py against a fake `az` runner (no Graph, no network)."""

from __future__ import annotations

import copy
import importlib.util
import json
import re
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType
from typing import Any

import httpx
import pytest

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "gates" / "entra_admin_mapping.py"
APP = "11111111-1111-4111-8111-111111111111"
TENANT = "22222222-2222-4222-8222-222222222222"
APP_OBJ = "33333333-3333-4333-8333-333333333333"
SP_OBJ = "44444444-4444-4444-8444-444444444444"
USER_OBJ = "55555555-5555-4555-8555-555555555555"
GROUP_OBJ = "66666666-6666-4666-8666-666666666666"
UPN = "owner@contoso.example"
FAKE_BEARER = "eyJhbGciOiJSUzI1NiJ9.fake.sig"
SECRETISH = re.compile(r"eyJ|bearer|secret|password|token=", re.IGNORECASE)
APPROVED = {"NS_LIVE_APPROVED": "1"}


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("entra_admin_mapping_under_test", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


mod = _load()


class FakeAz:
    def __init__(
        self,
        *,
        cloud: str = "AzureCloud",
        roles: list[dict[str, Any]] | None = None,
        group_refusal: str | None = None,
        token_ok: bool = True,
    ) -> None:
        self.cloud = cloud
        self.app: dict[str, Any] = {"id": APP_OBJ, "appId": APP, "appRoles": roles or []}
        self.assignments: list[dict[str, Any]] = []
        self.group_refusal = group_refusal
        self.token_ok = token_ok
        self.argv: list[list[str]] = []
        self.calls: list[tuple[str, str]] = []

    @property
    def writes(self) -> list[tuple[str, str]]:
        return [c for c in self.calls if c[0] in ("patch", "post", "put", "delete")]

    def __call__(self, args: Sequence[str], body: Mapping[str, Any] | None = None) -> str:
        argv = list(args)
        self.argv.append(argv)
        if argv[:2] == ["cloud", "show"]:
            return self.cloud + "\n"
        if argv[:2] == ["account", "show"]:
            return TENANT + "\n"
        if argv[:2] == ["account", "get-access-token"]:
            if not self.token_ok:
                raise mod.AzCallError(1, "token_refused")
            return FAKE_BEARER + "\n"
        assert argv[0] == "rest", argv
        method = argv[argv.index("--method") + 1]
        url = argv[argv.index("--url") + 1]
        self.calls.append((method, url))
        path = url.split("?")[0]
        if method == "get" and "/applications(" in url:
            return json.dumps(copy.deepcopy(self.app))
        if method == "get" and "/servicePrincipals(appId" in url:
            return json.dumps({"id": SP_OBJ})
        if method == "get" and path.endswith("/appRoleAssignedTo"):
            return json.dumps({"value": self.assignments})
        if method == "get" and "/groups/" in url:
            return json.dumps({"id": GROUP_OBJ})
        if method == "get" and "/users/" in url:
            return json.dumps({"id": USER_OBJ})
        if method == "patch" and path.endswith(f"/applications/{APP_OBJ}"):
            assert body is not None
            self.app["appRoles"] = copy.deepcopy(body["appRoles"])
            return ""
        if method == "post" and path.endswith("/appRoleAssignedTo"):
            assert body is not None
            if body["principalId"] == GROUP_OBJ and self.group_refusal is not None:
                raise mod.AzCallError(1, mod.classify_az_error(self.group_refusal))
            self.assignments.append(dict(body))
            return json.dumps({"id": "assignment"})
        raise AssertionError(f"unexpected call {method} {url}")


def base(cmd: str, cloud: str = "commercial") -> list[str]:
    return [cmd, "--cloud", cloud, "--app-id", APP, "--tenant-id", TENANT]


def apply_args(*extra: str, cloud: str = "commercial") -> list[str]:
    return [*base("apply", cloud), "--approve", "entra-app", *extra]


def test_plan_is_default_and_sends_reads_only(capsys: pytest.CaptureFixture[str]) -> None:
    fake = FakeAz()
    argv = ["--cloud", "commercial", "--app-id", APP, "--tenant-id", TENANT]
    assert mod.main([*argv, "--assign-user", UPN], az=fake, env={}) == 0
    out = capsys.readouterr().out
    assert fake.writes == []
    assert all(method == "get" for method, _ in fake.calls)
    assert all(url.startswith("https://graph.microsoft.com/v1.0/") for _, url in fake.calls)
    assert "appRoles before (values): []" in out
    assert 'appRoles after (values):  ["admin"]' in out
    assert "user -> admin app role: not assigned" in out
    assert USER_OBJ not in out and SP_OBJ not in out


def test_plan_reports_already_assigned(capsys: pytest.CaptureFixture[str]) -> None:
    role = {"id": mod.role_id("admin"), "value": "admin", "allowedMemberTypes": ["User"]}
    fake = FakeAz(roles=[role])
    fake.assignments.append(
        {"principalId": GROUP_OBJ, "resourceId": SP_OBJ, "appRoleId": mod.role_id("admin")}
    )
    assert mod.main([*base("plan"), "--group-object-id", GROUP_OBJ], az=fake, env={}) == 0
    out = capsys.readouterr().out
    assert "group -> admin app role: assigned" in out
    assert "would add app role: none" in out
    assert fake.writes == []


@pytest.mark.parametrize(
    ("env", "extra"),
    [
        ({}, ["--approve", "entra-app"]),
        ({"NS_LIVE_APPROVED": "0"}, ["--approve", "entra-app"]),
        (APPROVED, []),
        (APPROVED, ["--approve", "something-else"]),
    ],
)
def test_apply_refuses_without_both_approvals(env: dict[str, str], extra: list[str]) -> None:
    fake = FakeAz()
    argv = [*base("apply"), *extra, "--assign-user", UPN]
    assert mod.main(argv, az=fake, env=env) == mod.EXIT_REFUSED
    assert fake.argv == []


def test_apply_refuses_without_a_principal() -> None:
    fake = FakeAz()
    assert mod.main(apply_args(), az=fake, env=APPROVED) == mod.EXIT_REFUSED
    assert fake.argv == []


def test_group_and_user_are_mutually_exclusive() -> None:
    with pytest.raises(SystemExit):
        mod.main(apply_args("--group-object-id", GROUP_OBJ, "--assign-user", UPN), az=FakeAz())


@pytest.mark.parametrize(
    ("active", "flag"),
    [("AzureUSGovernment", "commercial"), ("AzureCloud", "government")],
)
def test_apply_refuses_on_cloud_mismatch(
    active: str, flag: str, capsys: pytest.CaptureFixture[str]
) -> None:
    fake = FakeAz(cloud=active)
    argv = apply_args("--assign-user", UPN, cloud=flag)
    assert mod.main(argv, az=fake, env=APPROVED) == mod.EXIT_REFUSED
    assert fake.calls == []  # no Graph request on either host
    assert "active az cloud" in capsys.readouterr().err


def test_government_uses_only_the_government_graph_host() -> None:
    fake = FakeAz(cloud="AzureUSGovernment")
    argv = apply_args("--assign-user", UPN, cloud="government")
    assert mod.main(argv, az=fake, env=APPROVED) == 0
    assert fake.calls
    assert all(url.startswith("https://graph.microsoft.us/v1.0/") for _, url in fake.calls)


def test_apply_adds_missing_role_user_only_and_assigns_user(
    capsys: pytest.CaptureFixture[str],
) -> None:
    fake = FakeAz()
    assert mod.main(apply_args("--assign-user", UPN), az=fake, env=APPROVED) == 0
    [role] = fake.app["appRoles"]
    assert role["value"] == "admin" and role["allowedMemberTypes"] == ["User"]
    assert fake.assignments == [
        {"principalId": USER_OBJ, "resourceId": SP_OBJ, "appRoleId": mod.role_id("admin")}
    ]
    out = capsys.readouterr().out
    assert "changed: added the admin app role" in out
    assert "changed: assigned the user" in out


def test_apply_keeps_existing_roles_and_skips_present_role() -> None:
    foreign = {
        "allowedMemberTypes": ["User"],
        "description": "x",
        "displayName": "Admin",
        "id": "77777777-7777-4777-8777-777777777777",
        "isEnabled": True,
        "value": "admin",
        "origin": "Application",
    }
    fake = FakeAz(roles=[foreign])
    assert mod.main(apply_args("--group-object-id", GROUP_OBJ), az=fake, env=APPROVED) == 0
    assert [m for m, _ in fake.writes] == ["post"]  # no PATCH: the role exists
    assert fake.assignments[0]["appRoleId"] == foreign["id"]  # existing role id reused


def test_apply_assigns_group() -> None:
    fake = FakeAz()
    assert mod.main(apply_args("--group-object-id", GROUP_OBJ), az=fake, env=APPROVED) == 0
    assert [a["principalId"] for a in fake.assignments] == [GROUP_OBJ]


def test_second_apply_sends_no_write(capsys: pytest.CaptureFixture[str]) -> None:
    fake = FakeAz()
    assert mod.main(apply_args("--assign-user", UPN), az=fake, env=APPROVED) == 0
    first = len(fake.writes)
    assert first == 2
    capsys.readouterr()
    assert mod.main(apply_args("--assign-user", UPN), az=fake, env=APPROVED) == 0
    assert len(fake.writes) == first
    assert "nothing to do" in capsys.readouterr().out


def test_group_refused_for_missing_p1_says_so(capsys: pytest.CaptureFixture[str]) -> None:
    graph_text = "Bad Request: the tenant requires an Entra ID Premium license for this."
    fake = FakeAz(group_refusal=graph_text)
    argv = apply_args("--group-object-id", GROUP_OBJ)
    assert mod.main(argv, az=fake, env=APPROVED) == mod.EXIT_REFUSED
    err = capsys.readouterr().err
    assert "Entra ID P1" in err and "--assign-user" in err
    assert graph_text not in err
    assert fake.assignments == []


def test_classify_az_error() -> None:
    assert mod.classify_az_error("requires a premium LICENSE") == "license_required"
    assert mod.classify_az_error("Authorization_RequestDenied") == "insufficient_privileges"
    assert mod.classify_az_error("AADSTS65001 consent") == "token_refused"
    assert mod.classify_az_error("boom") == "az_failed"


def test_apply_prints_mapping_and_no_ids_or_token(capsys: pytest.CaptureFixture[str]) -> None:
    fake = FakeAz()
    assert mod.main(apply_args("--group-object-id", GROUP_OBJ), az=fake, env=APPROVED) == 0
    cap = capsys.readouterr()
    text = cap.out + cap.err
    expected = {
        "tenant_id": TENANT,
        "audience": APP,
        "entries": [
            {
                "id": "ns-admins",
                "claim": "roles",
                "value": "admin",
                "role": "admin",
                "domains": "all",
                "customer_control": True,
            }
        ],
    }
    assert json.dumps(expected, separators=(",", ":")) in text
    assert "param entraRoleMappings = {" in text and "customer_control: true" in text
    for oid in (APP_OBJ, SP_OBJ, GROUP_OBJ, USER_OBJ, mod.role_id("admin")):
        assert oid not in text
    assert not SECRETISH.search(text)


def test_bicep_render_matches_json() -> None:
    rendered = mod._bicep(mod.mapping_value(TENANT, APP))  # pyright: ignore[reportPrivateUsage]
    assert f"tenant_id: '{TENANT}'" in rendered
    assert "domains: 'all'" in rendered


def test_verify_reports_open_when_not_approved(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    fake = FakeAz()
    argv = [*base("verify"), "--base-url", "https://api.example"]
    assert mod.main(argv, az=fake, env={}, evidence_dir=tmp_path) == mod.EXIT_REFUSED
    assert "G-138 OPEN" in capsys.readouterr().err
    assert fake.argv == []
    assert list(tmp_path.iterdir()) == []


def test_verify_without_token_prints_manual_check(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    fake = FakeAz(token_ok=False)
    argv = [*base("verify"), "--base-url", "https://api.example"]
    assert mod.main(argv, az=fake, env=APPROVED, evidence_dir=tmp_path) == mod.EXIT_OPEN
    cap = capsys.readouterr()
    assert "G-138 OPEN" in cap.err and "Manual check" in cap.out
    assert list(tmp_path.iterdir()) == []


def test_verify_approved_writes_evidence_without_token(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.path)
        assert request.headers["Authorization"] == "Bearer " + FAKE_BEARER
        if request.url.path == "/api/v1/me/access":
            return httpx.Response(
                200,
                json={
                    "roles": [{"role": "admin", "source": "entra_app_role", "domain_count": 3}],
                    "mapping_configured": True,
                    "groups_overage": False,
                },
            )
        return httpx.Response(200, json={"ok": True})

    argv = [*base("verify"), "--base-url", "https://api.example"]
    code = mod.main(
        argv,
        az=FakeAz(),
        env=APPROVED,
        transport=httpx.MockTransport(handler),
        evidence_dir=tmp_path,
        now=lambda: datetime(2026, 11, 18, 12, 0, tzinfo=UTC),
    )
    assert code == 0
    assert seen == ["/api/v1/me/access", "/api/v1/admin/system/status"]
    [evidence] = list(tmp_path.iterdir())
    text = evidence.read_text(encoding="utf-8")
    data = json.loads(text)
    assert data["result"] == "PASS"
    assert data["checks"]["/api/v1/me/access"]["roles"] == [
        {"role": "admin", "source": "entra_app_role"}
    ]
    cap = capsys.readouterr()
    for blob in (text, cap.out, cap.err):
        assert not SECRETISH.search(blob)
        assert TENANT not in blob and APP not in blob


def test_verify_refuses_plain_http_remote() -> None:
    argv = [*base("verify"), "--base-url", "http://api.example"]
    assert mod.main(argv, az=FakeAz(), env=APPROVED) == mod.EXIT_REFUSED


def test_never_runs_az_deployment() -> None:
    fake = FakeAz()
    mod.main([*base("plan"), "--assign-user", UPN], az=fake, env={})
    mod.main(apply_args("--group-object-id", GROUP_OBJ), az=fake, env=APPROVED)
    mod.main(apply_args("--assign-user", UPN), az=fake, env=APPROVED)
    assert fake.argv
    assert not any("deployment" in argv for argv in fake.argv)
    assert re.search(r"[\"']deployment[\"']", SCRIPT.read_text(encoding="utf-8")) is None
