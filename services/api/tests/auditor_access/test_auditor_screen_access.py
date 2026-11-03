"""Which Auditor-walkthrough screens can the ``security_auditor`` role actually reach? (issue #156)

``docs/walkthroughs/auditor.md`` listed ``/actions``, ``/actions/detail`` and ``/reconciliation``
for the Auditor. ``security_auditor`` holds ``audit.read`` and ``evidence.read`` and NO
``data.read`` (auditors read evidence, not data). This file issues, through the real FastAPI app
(dev-issuer tokens, in-memory policy store, no network), every API call each screen makes on load:

Call -> auditor / steward (all GET under /api/v1):
  me/domains (domain picker)            -> 403 permission_missing  / 200
  actions/domains/{d}/intents           -> 403 target_out_of_scope / 200
  actions/emergency-disable             -> 403 permission_missing  / 200
  actions/domains/{d}/intents/{id}      -> 403 target_out_of_scope / 404 (authorized, unknown id)
  reconciliation/domains/{d}            -> 403 target_out_of_scope / 200
  audit/domains, /{d}/records, /verify  -> 200 / 403
  catalog/curation/edges/{id}/observations (evidence.read, no screen) -> not 403 / 403

The denial is the intended fail-closed behaviour, not a defect: the Auditor walkthrough therefore
lists only the screens the role can reach. Permissions, routers and auth code are unchanged.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from action_plane_harness import make_api  # pyright: ignore[reportMissingImports]
from authz.authz_helpers import (  # pyright: ignore[reportMissingImports]
    FINANCE,
    Harness,
    policy,
    role,
)
from neurosphere_api.reconciliation import get_now
from neurosphere_core.aggregates import InMemoryAggregateStore
from neurosphere_core.auth.scope import Role

STEWARD = "a05b6c7d-8e9f-4a01-b2c3-d4e5f6a7b8aa"  # steward of FINANCE (harness ALICE)
AUDITOR = "b16c7d8e-9fa0-4b12-83d4-e5f6a7b8c9bb"  # security_auditor of FINANCE, nothing else

DOMAIN = FINANCE
ME_DOMAINS = "/api/v1/me/domains"
INTENTS = f"/api/v1/actions/domains/{DOMAIN}/intents"
INTENT = f"{INTENTS}/00000000-0000-4000-8000-0000000000aa"
EMERGENCY = "/api/v1/actions/emergency-disable"
RECONCILIATION = f"/api/v1/reconciliation/domains/{DOMAIN}"
AUDIT_DOMAINS = "/api/v1/audit/domains"
AUDIT_RECORDS = f"{AUDIT_DOMAINS}/{DOMAIN}/records"
AUDIT_VERIFY = f"{AUDIT_DOMAINS}/{DOMAIN}/verify"
EVIDENCE = "/api/v1/catalog/curation/edges/edge-1/observations"


def _world() -> Harness:
    api = make_api()
    h: Harness = api.h
    h.repo.put_principal(policy(STEWARD, role(Role.DOMAIN_STEWARD, DOMAIN)))
    h.repo.put_principal(policy(AUDITOR, role(Role.SECURITY_AUDITOR, DOMAIN)))
    h.app.state.aggregate_reader = InMemoryAggregateStore()
    h.app.dependency_overrides[get_now] = lambda: datetime.now(UTC)
    return h


def _get(h: Harness, who: str, path: str) -> tuple[int, str | None]:
    response = h.client.get(path, headers=h.auth(who))
    reason = None
    if response.headers.get("content-type", "").startswith("application/problem+json"):
        reason = response.json().get("reason")
    return response.status_code, reason


# Screens the Auditor CANNOT reach: every load-time call needs data.read, which the role lacks.
DATA_READ_CALLS = [
    # (path, reason): routes without a domain target say permission_missing; domain-addressed
    # routes say target_out_of_scope (the permission is absent on that domain).
    pytest.param(ME_DOMAINS, "permission_missing", id="me-domains"),
    pytest.param(INTENTS, "target_out_of_scope", id="actions-list"),
    pytest.param(EMERGENCY, "permission_missing", id="actions-emergency-disable"),
    pytest.param(INTENT, "target_out_of_scope", id="actions-detail"),
    pytest.param(RECONCILIATION, "target_out_of_scope", id="reconciliation"),
]


@pytest.mark.parametrize(("path", "reason"), DATA_READ_CALLS)
def test_auditor_is_forbidden_on_data_read_screens(path: str, reason: str) -> None:
    h = _world()
    assert _get(h, AUDITOR, path) == (403, reason)


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        pytest.param(ME_DOMAINS, 200, id="me-domains"),
        pytest.param(INTENTS, 200, id="actions-list"),
        pytest.param(EMERGENCY, 200, id="actions-emergency-disable"),
        # Authorized, then the unknown intent id is a 404: the harness works and 403 is the role.
        pytest.param(INTENT, 404, id="actions-detail"),
        pytest.param(RECONCILIATION, 200, id="reconciliation"),
    ],
)
def test_steward_reaches_the_same_calls(path: str, expected: int) -> None:
    h = _world()
    status, _ = _get(h, STEWARD, path)
    assert status == expected


# Screens the Auditor CAN reach: audit.read.
@pytest.mark.parametrize("path", [AUDIT_DOMAINS, AUDIT_RECORDS, AUDIT_VERIFY])
def test_auditor_reaches_the_audit_screen(path: str) -> None:
    h = _world()
    status, _ = _get(h, AUDITOR, path)
    assert status == 200


@pytest.mark.parametrize(
    ("path", "reason"),
    [
        (AUDIT_DOMAINS, "permission_missing"),
        (AUDIT_RECORDS, "target_out_of_scope"),
        (AUDIT_VERIFY, "target_out_of_scope"),
        (EVIDENCE, "permission_missing"),
    ],
)
def test_steward_lacks_audit_and_evidence_read(path: str, reason: str) -> None:
    # The permissions are disjoint: stewards read data, auditors read evidence.
    h = _world()
    assert _get(h, STEWARD, path) == (403, reason)


def test_auditor_is_authorized_for_evidence_read() -> None:
    # evidence.read has an API route but no frontend screen. Authorization passes (not 403); the
    # catalog repository is not wired in this harness, so the handler answers after the gate.
    h = _world()
    status, _ = _get(h, AUDITOR, EVIDENCE)
    assert status != 403
    assert status != 401
