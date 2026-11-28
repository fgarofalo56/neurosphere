"""PRP-104 item 7 (criteria 4 and 6): who may read or export captured content, per path.

Every content path is driven over ONE world (``security.interaction_access._world``: the real
interaction and replay routers on the PRP-06 dev-issuer harness, one spying store, audit and
denial log): the content read (``POST .../content-reads``), export create, export manifest,
export bundle and the replay payload branch (``include_payload=true`` with a purpose).

For each refused caller dimension of criterion 4 the content and export paths answer 403 with a
denied-attempt record naming the permission, and NOTHING is decrypted (no record decrypt, no
bundle unwrap) and no audit record is appended. The replay route keeps its pre-PRP-104 contract
(criterion 7): a caller without ``interaction.read`` in the domain gets the payload-free detail,
and one without ``data.read`` there gets 403; either way zero decrypts. A missing or unknown
purpose is 422 before any read and before any audit append. Positive controls prove each path
really returns content to the unexpired investigator of the domain, so no refusal is vacuous.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final, Literal

import pytest

from ..interaction_access._world import (
    ADMIN,
    ANALYST,
    AUDITOR,
    BODY,
    CUSTOMER,
    EXPIRING,
    EXPIRY_SECONDS,
    FINANCE,
    GOV_FINANCE,
    INVESTIGATOR,
    INVESTIGATOR_ONLY,
    OPS_INVESTIGATOR,
    OPS_INVESTIGATOR_FIN_VIEWER,
    OTHER_CUSTOMER_FINANCE,
    PURPOSE,
    PURPOSE_PARAMS,
    STEWARD,
    VIEWER,
    World,
    clean_env,
    payload_spans,
)

CONTENT_PATHS: Final = ("content_read", "export_create", "export_manifest", "export_bundle")
PERMISSION: Final = {
    "content_read": "interaction.read",
    "export_create": "interaction.export",
    "export_manifest": "interaction.export",
    "export_bundle": "interaction.export",
}

Replay = Literal["403", "payload_free", "refused"]


@dataclass(frozen=True)
class Case:
    """One refused caller dimension (criterion 4)."""

    who: str
    domain: str = FINANCE
    #: (cloud, customer) of the deployment's explorer when it is not the caller's.
    deployment: tuple[str, str] | None = None
    expired: bool = False
    #: Expected 403 reason on the content and export paths (None: any, but recorded).
    reason: str | None = "target_out_of_scope"
    #: Replay outcome: 403 (no data.read in the domain), the payload-free detail, or either.
    replay: Replay = "payload_free"


CASES: Final[dict[str, Case]] = {
    "admin": Case(ADMIN),
    "security-auditor": Case(AUDITOR, replay="refused"),
    "domain-steward": Case(STEWARD),
    "analyst": Case(ANALYST),
    "viewer": Case(VIEWER),
    "expired-investigator": Case(EXPIRING, expired=True, reason=None),
    "investigator-of-another-domain": Case(OPS_INVESTIGATOR, replay="403"),
    "investigator-of-another-domain-viewer-here": Case(OPS_INVESTIGATOR_FIN_VIEWER),
    "another-customer": Case(INVESTIGATOR, domain=OTHER_CUSTOMER_FINANCE, replay="403"),
    "another-cloud": Case(INVESTIGATOR, domain=GOV_FINANCE, replay="403"),
    # The caller is an unexpired FINANCE investigator, but the deployment is another tenancy.
    # Replay: the tenancy check sits in the content reader, so this is 403 today, not the
    # payload-free detail (PRP-104 execution state row 5 follow-up); both are refusals.
    "deployment-of-another-customer": Case(
        INVESTIGATOR,
        deployment=("commercial", "fabrikam"),
        reason="tenancy_mismatch",
        replay="refused",
    ),
    "deployment-of-another-cloud": Case(
        INVESTIGATOR,
        deployment=("government", CUSTOMER),
        reason="tenancy_mismatch",
        replay="refused",
    ),
    "investigator-without-data-read": Case(
        INVESTIGATOR_ONLY, reason="domain_not_readable", replay="403"
    ),
}


@pytest.fixture(autouse=True)
def _env(monkeypatch: pytest.MonkeyPatch) -> None:
    clean_env(monkeypatch)


@dataclass
class Setup:
    world: World
    ids: list[str]
    marks: list[str]
    export_id: str


def _setup(tmp_path: Path, case: Case | None = None, *, audit_fails: bool = False) -> Setup:
    world = World(tmp_path, audit_fails=audit_fails)
    ids, marks = world.seed_marked(2)
    export_id = ""
    if not audit_fails:
        owner = EXPIRING if case is not None and case.expired else INVESTIGATOR
        export_id = world.created(owner).export_id.root
    if case is not None and case.expired:
        world.h.clock.advance(EXPIRY_SECONDS + 60)
    if case is not None and case.deployment is not None:
        world.retarget(cloud=case.deployment[0], customer_id=case.deployment[1])
    world.denials.attempts.clear()
    return Setup(world, ids, marks, export_id)


def _call(s: Setup, path: str, who: str, domain: str = FINANCE, body: Any = None) -> Any:
    w = s.world
    calls: dict[str, Callable[[], Any]] = {
        "content_read": lambda: w.read(
            who, s.ids[0], domain=domain, body=PURPOSE if body is None else body
        ),
        "export_create": lambda: w.create(who, domain=domain, body=BODY if body is None else body),
        "export_manifest": lambda: w.manifest(who, s.export_id, domain=domain),
        "export_bundle": lambda: w.bundle(who, s.export_id, domain=domain),
    }
    return calls[path]()


# --- positive controls ----------------------------------------------------------------------------


@pytest.mark.parametrize("path", CONTENT_PATHS)
def test_the_investigator_of_the_domain_is_served(tmp_path: Path, path: str) -> None:
    s = _setup(tmp_path)
    decrypts, unwraps, _ = s.world.counters()
    response = _call(s, path, INVESTIGATOR)
    assert response.status_code in (200, 201), response.text
    assert response.headers["cache-control"] == "no-store"
    if path == "content_read":
        assert s.marks[0] in response.text
        assert s.world.store.content_reads == decrypts + 1
        assert s.world.events[-2:] == ["audit:interaction.read", f"decrypt:{s.ids[0]}"]
    if path == "export_bundle":
        assert all(mark in response.text for mark in s.marks)
        assert s.world.wrapper.unwraps == unwraps + 1
        assert s.world.events[-2:] == ["audit:interaction.export_download", "unwrap"]
    assert s.world.denials.attempts == []


def test_the_investigator_of_the_domain_gets_replay_payloads(tmp_path: Path) -> None:
    s = _setup(tmp_path)
    decrypts = s.world.store.content_reads
    response = s.world.trace(INVESTIGATOR, include_payload="true", **PURPOSE_PARAMS)
    assert response.status_code == 200, response.text
    assert all(mark in response.text for mark in s.marks)
    assert s.world.store.content_reads == decrypts + 2
    assert s.world.events[-3:] == [
        "audit:interaction.read",
        f"decrypt:{s.ids[0]}",
        f"decrypt:{s.ids[1]}",
    ]


# --- refusals: content read and export ------------------------------------------------------------


@pytest.mark.parametrize("path", CONTENT_PATHS)
@pytest.mark.parametrize("case_id", sorted(CASES))
def test_refused_caller_gets_403_a_denial_record_and_nothing_decrypted(
    tmp_path: Path, path: str, case_id: str
) -> None:
    case = CASES[case_id]
    s = _setup(tmp_path, case)
    before = s.world.counters()
    response = _call(s, path, case.who, case.domain)
    assert response.status_code == 403, response.text
    reason = response.json()["reason"]
    if case.reason is not None:
        assert reason == case.reason
    assert not any(mark in response.text for mark in s.marks)
    (attempt,) = s.world.denials.attempts
    assert attempt.permission == PERMISSION[path]
    assert attempt.reason == reason
    # Zero decrypts, zero bundle unwraps, zero audit appends.
    assert s.world.counters() == before


# --- refusals: the replay payload branch ----------------------------------------------------------


@pytest.mark.parametrize("case_id", sorted(CASES))
def test_refused_caller_never_gets_a_replay_payload(tmp_path: Path, case_id: str) -> None:
    case = CASES[case_id]
    s = _setup(tmp_path, case)
    before = s.world.counters()
    response = s.world.trace(case.who, domain=case.domain, include_payload="true", **PURPOSE_PARAMS)
    expected = {"403": {403}, "payload_free": {200}, "refused": {200, 403}}[case.replay]
    assert response.status_code in expected, response.text
    assert not any(mark in response.text for mark in s.marks)
    if response.status_code == 200:
        payloads = list(payload_spans(response))
        assert payloads and all(p is None for p in payloads)
    else:
        assert len(s.world.denials.attempts) == 1  # require() or the reader recorded it
    assert s.world.store.content_reads == before[0]
    assert s.world.counters() == before


# --- 422: purpose before anything -----------------------------------------------------------------

BAD_PURPOSES: Final = {
    "missing": None,
    "empty": {},
    "unknown-code": {"purpose_code": "curiosity", "case_ref": None},
    "blank-code": {"purpose_code": "", "case_ref": None},
    "case-ref-only": {"case_ref": "INC-1"},
}


@pytest.mark.parametrize("bad", sorted(BAD_PURPOSES))
@pytest.mark.parametrize("path", ["content_read", "export_create", "replay"])
def test_missing_or_unknown_purpose_is_422_before_any_read(
    tmp_path: Path, path: str, bad: str
) -> None:
    s = _setup(tmp_path)
    before = s.world.counters()
    purpose = BAD_PURPOSES[bad]
    w = s.world
    if path == "content_read":
        if purpose is None:
            response = w.h.client.post(
                f"/api/v1/domains/{FINANCE}/interactions/{s.ids[0]}/content-reads",
                headers=w.h.auth(INVESTIGATOR),
            )
        else:
            response = w.read(INVESTIGATOR, s.ids[0], body=purpose)
    elif path == "export_create":
        body = {"filters": BODY["filters"]}
        if purpose is not None:
            body["purpose"] = purpose
        response = w.create(INVESTIGATOR, body=body)
    else:
        params = {k: v for k, v in (purpose or {}).items() if v is not None}
        reads = w.reader.trace_reads
        response = w.trace(INVESTIGATOR, include_payload="true", **params)
        assert w.reader.trace_reads == reads  # refused before the trace is read
    assert response.status_code == 422, response.text
    assert not any(mark in response.text for mark in s.marks)
    assert w.counters() == before  # zero decrypts, zero unwraps, zero audit appends
    assert w.denials.attempts == []


# --- fail closed: no audit record, no content -----------------------------------------------------


@pytest.mark.parametrize("path", ["content_read", "export_create", "replay"])
def test_an_unwritable_audit_record_means_nothing_is_decrypted(tmp_path: Path, path: str) -> None:
    s = _setup(tmp_path, audit_fails=True)
    w = s.world
    if path == "replay":
        response = w.trace(INVESTIGATOR, include_payload="true", **PURPOSE_PARAMS)
    else:
        response = _call(s, path, INVESTIGATOR)
    assert response.status_code == 503, response.text
    assert response.json()["reason"] == "audit_write_failed"
    assert not any(mark in response.text for mark in s.marks)
    assert w.store.content_reads == 0
    assert w.audit.attempts >= 1  # it was tried, first


def test_an_unwritable_download_record_means_the_bundle_stays_sealed(tmp_path: Path) -> None:
    s = _setup(tmp_path)
    s.world.audit.fail = True
    unwraps = s.world.wrapper.unwraps
    response = _call(s, "export_bundle", INVESTIGATOR)
    assert response.status_code == 503, response.text
    assert not any(mark in response.text for mark in s.marks)
    assert s.world.wrapper.unwraps == unwraps
