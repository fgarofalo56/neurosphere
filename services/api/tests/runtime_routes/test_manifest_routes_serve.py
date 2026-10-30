"""PRP-29 item 11: no route behind a manifest page answers a ``*_unconfigured`` 503 once composed.

CI-safe: the REAL default builders (authz, data, planes, copilot, mcp, edge) over in-memory
backends handed in through ``CompositionOverrides``, plus a test-only dev-issuer authenticator
(pattern: ``runtime_api``/``runtime_data``/``runtime_planes``). No emulator, no network, no live
model. The calls come from ``manifest_calls`` (derived from the frontend api modules) and the
route list is pinned to ``frontend/src/app/route-manifest.json``.

What this proves is wiring, not data: an empty in-memory backend answers 200 with an empty page,
which is fine here (the emulator suite ``tests/integration/real_stack/test_manifest_routes.py``
checks the data). What must never happen is the composed app answering 503 ``<x>_unconfigured``
for a route a page depends on, because that means a builder left a collaborator unwired.
"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path
from typing import Any, Final

import pytest
from authz.authz_helpers import (  # pyright: ignore[reportMissingImports]
    FINANCE,
    OPERATIONS,
    POLICY_VERSION,
    FakeClock,
    role,
)
from neurosphere_api.runtime import CompositionOverrides
from neurosphere_api.runtime.builders import default_builders
from neurosphere_api.sandbox.repository import SandboxRepository
from neurosphere_core.auth.scope import (
    InMemoryPolicyRepository,
    PolicyHead,
    PrincipalPolicy,
    Role,
    principal_document_id,
)
from neurosphere_core.gateway import InMemoryGatewayStore
from runtime_api.runtime_helpers import (  # pyright: ignore[reportMissingImports]
    ALICE,
    CUSTOMER,
    Composed,
    compose,
    composed_principal_id,
    configure_auth_env,
)
from runtime_data.data_helpers import data_overrides  # pyright: ignore[reportMissingImports]
from runtime_planes.planes_helpers import (  # pyright: ignore[reportMissingImports]
    ch,
    plane_backends,
)

from runtime_routes.manifest_calls import (  # pyright: ignore[reportMissingImports]
    COPILOT_ROUTES_503,
    DOMAINS_CALL,
    MANIFEST_CALLS,
    ApiCall,
)

MANIFEST: Final = (
    Path(__file__).resolve().parents[4] / "frontend" / "src" / "app" / "route-manifest.json"
)
ALL_ROLES: Final = (
    Role.VIEWER,
    Role.ANALYST,
    Role.DOMAIN_STEWARD,
    Role.SECURITY_AUDITOR,
    Role.ADMIN,
)


class _EmptySandboxStore:
    """The sandbox store slice over an empty sandbox database."""

    async def count(self, database: str, container: str, kind: str | None) -> int:
        return 0

    async def list_items(
        self, database: str, container: str, kind: str, limit: int, offset: int
    ) -> list[dict[str, Any]]:
        return []

    async def clear(self, database: str, container: str) -> int:
        return 0


def _operator_policy() -> InMemoryPolicyRepository:
    """ALICE holds every role over the two test domains (the calls need steward/admin/auditor)."""
    pid = composed_principal_id(ALICE)
    repo = InMemoryPolicyRepository()
    repo.put_head(PolicyHead(customer_id=CUSTOMER, policy_version=POLICY_VERSION))
    repo.put_principal(
        PrincipalPolicy(
            id=principal_document_id(pid),
            customer_id=CUSTOMER,
            principal_id=pid,
            domain_memberships=(FINANCE, OPERATIONS),
            role_assignments=tuple(role(r, FINANCE, OPERATIONS) for r in ALL_ROLES),
        )
    )
    return repo


def _no_arm(profile: object) -> object:
    raise AssertionError("the manifest pages never call ARM")


def _composed(
    monkeypatch: pytest.MonkeyPatch, *, copilot: bool, without: tuple[str, ...] = ()
) -> Composed:
    configure_auth_env(monkeypatch)
    clock = FakeClock()
    base = data_overrides(clock, without=without)
    backends = {
        **base.backends,
        **plane_backends(),
        # The gateway plane (PRP-33 builder) composes over an in-memory store; the /gateways page
        # (PRP-34 item 8) only lists, so no ARM client is ever built.
        "gateway_store": InMemoryGatewayStore(),
        "gateway_arm_factory": _no_arm,
        "sandbox_repository": SandboxRepository(_EmptySandboxStore()),
    }
    overrides: CompositionOverrides = dataclasses.replace(
        base,
        policy_repository=_operator_policy(),
        model_adapter=ch.ScriptedAdapter(ch.say("Nothing changed.")) if copilot else None,
        backends=backends,
    )
    return compose(overrides, builders=default_builders(), clock=clock)


def _fill(call: ApiCall, domain: str) -> str:
    path = call.path.replace("{domain}", domain)
    for need in call.needs:
        path = path.replace("{" + need + "}", "unknown")
    return path


def _unconfigured(response: Any) -> str | None:
    if response.status_code != 503:
        return None
    reason = response.json().get("reason", "")
    return reason if str(reason).endswith("_unconfigured") else None


def test_the_call_map_covers_exactly_the_manifest() -> None:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))["routes"]
    assert len(manifest) == 28
    assert sorted(MANIFEST_CALLS) == sorted(manifest)
    assert all(DOMAINS_CALL in calls for calls in MANIFEST_CALLS.values())


def test_no_manifest_route_answers_an_unconfigured_503(monkeypatch: pytest.MonkeyPatch) -> None:
    composed = _composed(monkeypatch, copilot=True)
    headers = composed.auth(ALICE)
    offenders: list[str] = []
    server_errors: list[str] = []
    denied: list[str] = []
    with composed.client() as client:
        for route, calls in sorted(MANIFEST_CALLS.items()):
            for call in calls:
                path = _fill(call, FINANCE)
                response = client.get(path, params=list(call.query), headers=headers)
                label = f"{route} -> {path} [{response.status_code}]"
                reason = _unconfigured(response)
                if reason is not None:
                    offenders.append(f"{label} {reason}")
                elif response.status_code >= 500:
                    server_errors.append(f"{label} {response.text[:160]}")
                elif response.status_code in (401, 403):
                    denied.append(f"{label} {response.text[:160]}")
    assert not offenders, "unwired collaborators:\n" + "\n".join(offenders)
    assert not server_errors, "server errors:\n" + "\n".join(server_errors)
    assert not denied, "the operator holds every role, so nothing may be denied:\n" + "\n".join(
        denied
    )


def test_the_shell_domain_list_is_served(monkeypatch: pytest.MonkeyPatch) -> None:
    composed = _composed(monkeypatch, copilot=True)
    with composed.client() as client:
        response = client.get(DOMAINS_CALL.path, headers=composed.auth(ALICE))
    assert response.status_code == 200, response.text
    assert {item["domain_id"] for item in response.json()["items"]} == {FINANCE, OPERATIONS}


def test_the_copilot_dock_is_served_with_a_scripted_adapter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    composed = _composed(monkeypatch, copilot=True)
    headers = composed.auth(ALICE)
    with composed.client() as client:
        for path in COPILOT_ROUTES_503:
            response = client.get(path, headers=headers)
            assert _unconfigured(response) is None, (path, response.text)
            assert response.status_code == 200, (path, response.text)


def test_copilot_stays_disabled_without_an_adapter(monkeypatch: pytest.MonkeyPatch) -> None:
    """The compose default (NS_COPILOT_MODE unset): the dock answers 503 copilot_unconfigured."""
    composed = _composed(monkeypatch, copilot=False)
    with composed.client() as client:
        response = client.get(COPILOT_ROUTES_503[0], headers=composed.auth(ALICE))
    assert response.status_code == 503, response.text
    assert response.json()["reason"] == "copilot_unconfigured"


def test_the_detector_sees_a_missing_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    """Negative control: leave the aggregates backend out and the dashboards must be flagged."""
    composed = _composed(monkeypatch, copilot=True, without=("aggregates",))
    call = MANIFEST_CALLS["/dashboards/cost"][1]
    with composed.client() as client:
        response = client.get(
            _fill(call, FINANCE), params=list(call.query), headers=composed.auth(ALICE)
        )
    assert _unconfigured(response) is not None, response.text
