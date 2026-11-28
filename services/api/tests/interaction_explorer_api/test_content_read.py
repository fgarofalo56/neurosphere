"""PRP-104 item 3: the audited content read (criteria 2, 3, 5).

Routes run over the PRP-06 authz harness (dev-issuer tokens, in-memory policy store, fake clock)
with an :class:`InMemoryInteractionStore` holding synthetic records. One shared ``events`` list
records the audit append and every decrypt, so the tests prove the ``interaction.read`` record is
durable BEFORE any content is decrypted. Synthetic data only: every canary is generated at
runtime. ``test_audit_fail_closed.py`` imports the harness from here.
"""

from __future__ import annotations

import asyncio
import secrets
import string
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import authz.authz_helpers as helpers  # pyright: ignore[reportMissingImports]
import pytest
from neurosphere_api.interactions import (
    PREFIX,
    ContentAccess,
    InteractionContentReader,
    InteractionExplorer,
    build_router,
    configure_interaction_explorer,
)
from neurosphere_contracts.audit.v1.audit_record import AuditRecord
from neurosphere_contracts.interactions.v1.interaction_record import InteractionRecord
from neurosphere_contracts.interactions.v1.redacted_content import RedactedContent
from neurosphere_core.audit import (
    ALLOW_DETAIL,
    AuditDraft,
    AuditRepository,
    InMemoryAuditStore,
    domain_audit_chain_id,
    sha256_digest,
)
from neurosphere_core.auth.scope import PolicyRoleAssignment, Role
from neurosphere_core.crypto import LocalFileKeyWrapper
from neurosphere_core.errors import (
    DependencyTransientError,
    ForbiddenError,
    InvalidSchemaError,
    NotFoundError,
)
from neurosphere_core.interactions import InMemoryInteractionStore
from neurosphere_core.lifecycle.policy import PolicyState, load_policy
from neurosphere_core.scope import IdentityScope

CUSTOMER: str = helpers.CUSTOMER
FINANCE: str = helpers.FINANCE
OPERATIONS: str = helpers.OPERATIONS
OTHER_CUSTOMER_FINANCE: str = helpers.OTHER_CUSTOMER_FINANCE
GOV_FINANCE: str = helpers.GOV_FINANCE
FIN_CHAIN = domain_audit_chain_id(CUSTOMER, FINANCE)
KEK_URI = "https://synthetic-kv.vault.azure.net/keys/ns-content-kek"
AGENT = f"commercial:{CUSTOMER}:foundry:agent:support-bot"
T_CAPTURE = datetime(2026, 11, 20, 10, 0, tzinfo=UTC)
PURPOSE = {"purpose_code": "incident_investigation", "case_ref": "INC-2026-0042"}


def object_id() -> str:
    return str(uuid.uuid4())


# Principals: the investigator who may read content holds the investigator role AND a viewer
# assignment in FINANCE (content is read only where the interaction can also be listed).
INVESTIGATOR = object_id()
INVESTIGATOR_ONLY = object_id()  # interaction.read in FINANCE, no data.read
OPS_INVESTIGATOR = object_id()  # investigator + viewer in OPERATIONS only
ADMIN = object_id()
AUDITOR = object_id()
STEWARD = object_id()
ANALYST = object_id()
VIEWER = object_id()
EXPIRING = object_id()  # investigator assignment that expires after 60 s
EXPIRY_SECONDS = 60


def canary() -> str:
    return "NSCANARY-" + "".join(secrets.choice(string.ascii_lowercase) for _ in range(16))


def card_number() -> str:
    return "4" + "".join(secrets.choice(string.digits) for _ in range(15))


def generated_secret() -> str:
    return "nsk_" + secrets.token_hex(20)


def stamp(value: datetime) -> str:
    return value.strftime("%Y-%m-%dT%H:%M:%SZ")


def new_id() -> str:
    return str(uuid.uuid4())


def retention() -> PolicyState:
    return load_policy(
        {
            "policy_version": "v1",
            "rules": [
                {
                    "data_class": "telemetry_event",
                    "min_retention_days": 0,
                    "max_retention_days": 30,
                },
                {
                    "data_class": "interaction_content",
                    "min_retention_days": 0,
                    "max_retention_days": 90,
                },
            ],
            "retain_prompt_response_bodies": True,
        }
    )


def record_doc(interaction_id: str, **overrides: Any) -> dict[str, Any]:
    doc: dict[str, Any] = {
        "schema_version": "1.2.0",
        "interaction_id": interaction_id,
        "cloud": "commercial",
        "customer_id": CUSTOMER,
        "domain_id": FINANCE,
        "source_id": "src-synthetic",
        "event_id": "evt-" + interaction_id[:8],
        "correlation_id": "corr-" + interaction_id[:8],
        "capture_source": "edge_push",
        "occurred_at": stamp(T_CAPTURE - timedelta(seconds=1)),
        "captured_at": stamp(T_CAPTURE),
        "agent_id": AGENT,
        "tool_id": None,
        "principal_id": None,
        "capture_policy_id": "support-capture",
        "capture_policy_version": 2,
        "detector_set_version": "detectors-1.0",
        "redaction_state": "redacted",
        "parts": [{"part": "prompt", "char_count": 40, "truncated": False}],
        "content_ref": None,
        "findings_summary": [{"category": "payment_card", "count": 1, "action": "replaced"}],
        "sensitivity_categories": ["pii"],
        "data_asset_ids": [],
        "expires_at": stamp(T_CAPTURE + timedelta(days=30)),
    }
    doc.update(overrides)
    return doc


def redacted(interaction_id: str, mark: str) -> RedactedContent:
    """What capture stores: the redaction already replaced the card and the secret."""
    return RedactedContent.model_validate(
        {
            "schema_version": "1.0.0",
            "interaction_id": interaction_id,
            "redaction_state": "redacted",
            "detector_set_version": "detectors-1.0",
            "parts": [
                {
                    "part": "prompt",
                    "text": (
                        f"{mark} card [[ns-redacted:payment_card]] "
                        "key [[ns-redacted:generated_secret]]"
                    ),
                    "truncated": False,
                    "findings": [],
                }
            ],
        }
    )


class SpyStore(InMemoryInteractionStore):
    """The real in-memory store that logs every decrypt into the shared ``events`` list."""

    def __init__(self, tmp_path: Path, events: list[str]) -> None:
        super().__init__(
            LocalFileKeyWrapper(tmp_path / "kek.bin"), kek_uri=KEK_URI, policy=retention()
        )
        self.events = events
        self.content_reads = 0
        self.purged: set[str] = set()

    async def get_metadata(
        self, customer_id: str, domain_id: str, interaction_id: str
    ) -> InteractionRecord | None:
        record = await super().get_metadata(customer_id, domain_id, interaction_id)
        if record is not None and interaction_id in self.purged:
            return record.model_copy(update={"content_ref": None})
        return record

    async def read_content(
        self, customer_id: str, domain_id: str, interaction_id: str
    ) -> RedactedContent:
        self.content_reads += 1
        self.events.append(f"decrypt:{interaction_id}")
        return await super().read_content(customer_id, domain_id, interaction_id)


class SpyAudit(AuditRepository):
    """The real repository over an in-memory store; logs each append, optionally fails it."""

    def __init__(self, events: list[str], *, fail: bool = False) -> None:
        super().__init__(InMemoryAuditStore())
        self.events = events
        self.fail = fail
        self.attempts = 0

    async def append(self, chain_id: str, draft: AuditDraft) -> AuditRecord:
        self.attempts += 1
        if self.fail:
            raise DependencyTransientError("audit store down", reason="audit_store_unavailable")
        record = await super().append(chain_id, draft)
        self.events.append(f"audit:{draft.operation}")
        return record


def investigator_role(
    *domains: str, expires_in: float = 3 * 24 * 3600, suffix: str = ""
) -> PolicyRoleAssignment:
    assignment = helpers.role(Role.INTERACTION_INVESTIGATOR, *domains, expires_in=expires_in)
    return assignment.model_copy(update={"assignment_id": assignment.assignment_id + suffix})


class Api:
    def __init__(
        self,
        tmp_path: Path,
        *,
        explorer: bool = True,
        audit_fails: bool = False,
        denial_error: Exception | None = None,
        cloud: str = "commercial",
        customer_id: str = CUSTOMER,
    ) -> None:
        self.events: list[str] = []
        self.store = SpyStore(tmp_path, self.events)
        self.audit = SpyAudit(self.events, fail=audit_fails)
        self.denials = helpers.RecordingDenials(denial_error)
        viewer_fin = helpers.role(Role.VIEWER, FINANCE)
        self.h = helpers.harness(
            helpers.policy(INVESTIGATOR, investigator_role(FINANCE), viewer_fin),
            helpers.policy(INVESTIGATOR_ONLY, investigator_role(FINANCE)),
            helpers.policy(
                OPS_INVESTIGATOR,
                investigator_role(OPERATIONS),
                helpers.role(Role.VIEWER, OPERATIONS),
            ),
            helpers.policy(ADMIN, helpers.role(Role.ADMIN, FINANCE)),
            helpers.policy(AUDITOR, helpers.role(Role.SECURITY_AUDITOR, FINANCE)),
            helpers.policy(STEWARD, helpers.role(Role.DOMAIN_STEWARD, FINANCE)),
            helpers.policy(ANALYST, helpers.role(Role.ANALYST, FINANCE)),
            helpers.policy(VIEWER, viewer_fin),
            helpers.policy(
                EXPIRING, investigator_role(FINANCE, expires_in=EXPIRY_SECONDS), viewer_fin
            ),
            routers={PREFIX: build_router()},
            denials=self.denials,
        )
        self.h.app.state.audit_repository = self.audit
        self.explorer = InteractionExplorer(
            store=self.store, audit=self.audit, cloud=cloud, customer_id=customer_id
        )
        if explorer:
            configure_interaction_explorer(self.h.app, self.explorer)

    def read(
        self,
        who: str,
        interaction_id: str,
        *,
        domain: str = FINANCE,
        body: Any = PURPOSE,
    ) -> Any:
        return self.h.client.post(
            f"{PREFIX}/{domain}/interactions/{interaction_id}/content-reads",
            json=body,
            headers=self.h.auth(who),
        )

    def records(self, chain: str = FIN_CHAIN) -> list[AuditRecord]:
        return list(asyncio.run(self.audit.read_range(chain, start=0, limit=100)))

    def seed(self, *interaction_ids: str, domain: str = FINANCE) -> list[str]:
        marks: list[str] = []

        async def put_all() -> None:
            for iid in interaction_ids:
                mark = canary()
                marks.append(mark)
                record = InteractionRecord.model_validate(record_doc(iid, domain_id=domain))
                await self.store.put(record, redacted(iid, mark), capture_retention_days=30)

        asyncio.run(put_all())
        return marks

    def scope_of(self, who: str) -> IdentityScope:
        """The scope ``who`` would get now (validator + deriver of the harness)."""

        async def derive() -> IdentityScope:
            claims = await self.h.validator.authenticate(f"Bearer {self.h.token(who)}")
            derivation = await self.h.deriver.derive(claims)
            return derivation.scope

        return asyncio.run(derive())

    def access(self, scope: IdentityScope, *, at_offset: float = 0.0) -> ContentAccess:
        return ContentAccess(
            scope=scope,
            now=datetime.fromtimestamp(self.h.clock.now + at_offset, UTC),
            request_id=str(uuid.uuid4()),
            method="GET",
            path="/api/v1/domains/x/traces/y",
            denials=self.denials,
        )


def purpose_state(ids: list[str], purpose: dict[str, Any] = PURPOSE) -> str:
    return sha256_digest(
        {
            "domain_id": FINANCE,
            "interaction_ids": ids,
            "purpose_code": purpose["purpose_code"],
            "case_ref": purpose["case_ref"],
        }
    )


def digest_of(record: AuditRecord) -> str:
    assert record.subject is not None
    assert record.subject.state_digest is not None
    return record.subject.state_digest.root


@pytest.fixture
def api(tmp_path: Path) -> Api:
    return Api(tmp_path)


# --- the allowed read -----------------------------------------------------------------------------


def test_content_read_appends_one_record_before_decrypting(api: Api) -> None:
    iid = new_id()
    (mark,) = api.seed(iid)
    response = api.read(INVESTIGATOR, iid)
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "no-store"
    body = RedactedContent.model_validate(response.json())
    stored = asyncio.run(InMemoryInteractionStore.read_content(api.store, CUSTOMER, FINANCE, iid))
    assert body == stored  # the stored redacted content, unchanged
    assert mark in response.text

    # Ordering: the interaction.read record is durable before the one decrypt.
    assert api.events == ["audit:interaction.read", f"decrypt:{iid}"]
    assert api.store.content_reads == 1

    (record,) = api.records()
    assert record.operation == "interaction.read"
    assert record.kind == "after"
    assert record.outcome is not None and record.outcome.detail == ALLOW_DETAIL
    assert record.channel == "rest"
    assert record.subject is not None
    assert record.subject.target.canonical_id == (
        f"commercial:{CUSTOMER}:neurosphere:interaction:{iid}"
    )
    assert record.subject.target.entity_type == "interaction"
    assert record.subject.snapshot_ref == f"interaction:{iid}"
    assert digest_of(record) == purpose_state([iid])
    assert record.correlation_id.startswith("corr-")
    scope = api.scope_of(INVESTIGATOR)
    assert record.actor.principal_pseudonym == scope.to_contract().principal.principal_pseudonym
    assert api.denials.attempts == []
    # Content-free record: no canary and no case reference in clear.
    dumped = record.model_dump_json()
    assert mark not in dumped
    assert "INC-2026-0042" not in dumped


def test_purpose_without_case_ref_is_bound_as_null(api: Api) -> None:
    iid = new_id()
    api.seed(iid)
    purpose = {"purpose_code": "legal_hold_review", "case_ref": None}
    assert api.read(INVESTIGATOR, iid, body=purpose).status_code == 200
    (record,) = api.records()
    assert record.subject is not None
    assert digest_of(record) == purpose_state([iid], purpose)
    # A different purpose yields a different digest: the purpose is really bound.
    assert digest_of(record) != purpose_state([iid])


def test_redacted_away_values_never_appear_in_the_response(api: Api) -> None:
    iid = new_id()
    card, secret = card_number(), generated_secret()
    # Capture redacted these before storing; only placeholders were ever written.
    api.seed(iid)
    response = api.read(INVESTIGATOR, iid)
    assert response.status_code == 200
    assert card not in response.text
    assert secret not in response.text
    assert "[[ns-redacted:payment_card]]" in response.text
    assert "[[ns-redacted:generated_secret]]" in response.text


# --- 422: purpose, before any read or audit -------------------------------------------------------


@pytest.mark.parametrize(
    "body",
    [
        None,
        {},
        {"case_ref": "INC-1"},
        {"purpose_code": "curiosity", "case_ref": None},
        {"purpose_code": "", "case_ref": None},
        {"purpose_code": "security_review", "case_ref": "see the ticket from last week"},
        {"purpose_code": "security_review", "case_ref": "someone@contoso.example"},
        {"purpose_code": "security_review", "case_ref": str(uuid.uuid4())},
        {"purpose_code": "security_review", "case_ref": None, "note": "why"},
    ],
    ids=[
        "no-body",
        "empty",
        "missing-code",
        "unknown-code",
        "blank-code",
        "prose-case-ref",
        "email-case-ref",
        "guid-case-ref",
        "extra-field",
    ],
)
def test_missing_or_invalid_purpose_is_422_with_no_read_and_no_audit(api: Api, body: Any) -> None:
    iid = new_id()
    (mark,) = api.seed(iid)
    response = api.read(INVESTIGATOR, iid, body=body)
    assert response.status_code == 422, response.text
    assert mark not in response.text
    assert api.store.content_reads == 0
    assert api.audit.attempts == 0
    assert api.records() == []
    assert api.denials.attempts == []


def test_reader_revalidates_a_constructed_purpose(api: Api) -> None:
    from neurosphere_contracts.interactions.v1.interaction_access_purpose import (
        InteractionAccessPurpose,
    )

    iid = new_id()
    api.seed(iid)
    forged = InteractionAccessPurpose.model_construct(purpose_code="curiosity", case_ref=None)
    reader = InteractionContentReader(api.explorer)
    access = api.access(api.scope_of(INVESTIGATOR))
    with pytest.raises(InvalidSchemaError) as caught:
        asyncio.run(reader.read(access, FINANCE, iid, forged))
    assert caught.value.reason == "interaction_purpose_invalid"
    assert api.store.content_reads == 0
    assert api.audit.attempts == 0


# --- 403: every refusal dimension, each with a denial record --------------------------------------


@pytest.mark.parametrize(
    ("who", "domain", "reason"),
    [
        (ADMIN, FINANCE, "target_out_of_scope"),
        (AUDITOR, FINANCE, "target_out_of_scope"),
        (STEWARD, FINANCE, "target_out_of_scope"),
        (ANALYST, FINANCE, "target_out_of_scope"),
        (VIEWER, FINANCE, "target_out_of_scope"),
        (OPS_INVESTIGATOR, FINANCE, "target_out_of_scope"),
        (INVESTIGATOR, OTHER_CUSTOMER_FINANCE, "target_out_of_scope"),
        (INVESTIGATOR, GOV_FINANCE, "target_out_of_scope"),
        (INVESTIGATOR_ONLY, FINANCE, "domain_not_readable"),
    ],
    ids=[
        "admin",
        "security-auditor",
        "steward",
        "analyst",
        "viewer",
        "investigator-of-another-domain",
        "another-customer",
        "another-cloud",
        "investigator-without-data-read",
    ],
)
def test_refused_callers_get_403_with_a_denial_record(
    api: Api, who: str, domain: str, reason: str
) -> None:
    iid = new_id()
    (mark,) = api.seed(iid)
    response = api.read(who, iid, domain=domain)
    assert response.status_code == 403, response.text
    assert response.json()["reason"] == reason
    assert mark not in response.text
    (attempt,) = api.denials.attempts
    assert attempt.permission == "interaction.read"
    assert attempt.reason == reason
    assert attempt.domain_id == domain
    assert api.store.content_reads == 0
    assert api.audit.attempts == 0


def test_expired_investigator_gets_403_with_a_denial_record(api: Api) -> None:
    iid = new_id()
    api.seed(iid)
    assert api.read(EXPIRING, iid).status_code == 200  # before expiry
    api.h.clock.advance(EXPIRY_SECONDS + 60)
    reads_before = api.store.content_reads
    response = api.read(EXPIRING, iid)
    assert response.status_code == 403
    (attempt,) = api.denials.attempts
    assert attempt.permission == "interaction.read"
    assert api.store.content_reads == reads_before
    assert len(api.records()) == 1  # only the pre-expiry read


def test_reader_judges_expiry_at_the_request_clock(api: Api) -> None:
    """A scope derived while the assignment was live grants nothing once ``now`` passes it."""
    iid = new_id()
    api.seed(iid)
    scope = api.scope_of(EXPIRING)
    reader = InteractionContentReader(api.explorer)
    with pytest.raises(ForbiddenError) as caught:
        asyncio.run(
            reader.read(api.access(scope, at_offset=EXPIRY_SECONDS + 1), FINANCE, iid, PURPOSE)
        )
    assert caught.value.reason == "permission_missing"
    (attempt,) = api.denials.attempts
    assert (attempt.permission, attempt.domain_id) == ("interaction.read", FINANCE)
    assert api.store.content_reads == 0
    assert api.audit.attempts == 0
    content = asyncio.run(reader.read(api.access(scope), FINANCE, iid, PURPOSE))
    assert content.interaction_id.root == iid


@pytest.mark.parametrize(
    ("cloud", "customer_id"),
    [("government", CUSTOMER), ("commercial", "fabrikam")],
    ids=["deployment-of-another-cloud", "deployment-of-another-customer"],
)
def test_caller_outside_the_deployment_tenancy_is_403(
    tmp_path: Path, cloud: str, customer_id: str
) -> None:
    api = Api(tmp_path, cloud=cloud, customer_id=customer_id)
    iid = new_id()
    api.seed(iid)
    response = api.read(INVESTIGATOR, iid)
    assert response.status_code == 403
    assert response.json()["reason"] == "tenancy_mismatch"
    (attempt,) = api.denials.attempts
    assert (attempt.permission, attempt.reason) == ("interaction.read", "tenancy_mismatch")
    assert api.store.content_reads == 0
    assert api.audit.attempts == 0


def test_failed_denial_record_on_the_post_is_503(tmp_path: Path) -> None:
    api = Api(tmp_path, denial_error=RuntimeError("denial store down"))
    iid = new_id()
    api.seed(iid)
    response = api.read(INVESTIGATOR_ONLY, iid)  # refused by the reader itself
    assert response.status_code == 503
    assert response.json()["reason"] == "audit_write_failed"
    assert api.store.content_reads == 0


def test_authorization_precedes_the_lookup(api: Api) -> None:
    response = api.read(VIEWER, new_id())  # absent AND not permitted -> 403, not 404
    assert response.status_code == 403
    assert len(api.denials.attempts) == 1


# --- 404 / 503 ------------------------------------------------------------------------------------


def test_absent_interaction_is_404_after_authz_with_no_record(api: Api) -> None:
    response = api.read(INVESTIGATOR, new_id())
    assert response.status_code == 404
    assert response.json()["reason"] == "interaction_not_found"
    assert api.audit.attempts == 0
    assert api.store.content_reads == 0
    assert api.denials.attempts == []


def test_interaction_of_another_domain_is_404(api: Api) -> None:
    iid = new_id()
    api.seed(iid, domain=OPERATIONS)
    response = api.read(INVESTIGATOR, iid)  # stored under OPERATIONS, asked under FINANCE
    assert response.status_code == 404
    assert api.store.content_reads == 0


def test_purged_content_is_404_with_no_record(api: Api) -> None:
    iid = new_id()
    api.seed(iid)
    api.store.purged.add(iid)
    response = api.read(INVESTIGATOR, iid)
    assert response.status_code == 404
    assert response.json()["reason"] == "interaction_content_purged"
    assert api.audit.attempts == 0
    assert api.store.content_reads == 0


def test_explorer_off_is_503(tmp_path: Path) -> None:
    api = Api(tmp_path, explorer=False)
    response = api.read(INVESTIGATOR, new_id())
    assert response.status_code == 503
    assert response.json()["reason"] == "interaction_explorer_unconfigured"
    assert api.audit.attempts == 0


def test_metadata_routes_are_unchanged_for_the_investigator(api: Api) -> None:
    iid = new_id()
    (mark,) = api.seed(iid)
    response = api.h.client.get(
        f"{PREFIX}/{FINANCE}/interactions/{iid}", headers=api.h.auth(INVESTIGATOR)
    )
    assert response.status_code == 200
    assert mark not in response.text
    assert api.store.content_reads == 0
    (record,) = api.records()
    assert record.operation == "interaction.metadata_read"


# --- batch ----------------------------------------------------------------------------------------


def test_read_many_writes_one_record_listing_every_id_before_any_decrypt(api: Api) -> None:
    ids = [new_id(), new_id(), new_id()]
    api.seed(*ids)
    absent = new_id()
    reader = InteractionContentReader(api.explorer)
    access = api.access(api.scope_of(INVESTIGATOR))
    result = asyncio.run(
        reader.read_many(access, FINANCE, [ids[0], absent, ids[1], ids[0], ids[2]], PURPOSE)
    )
    assert list(result) == ids
    assert api.events == ["audit:interaction.read"] + [f"decrypt:{i}" for i in ids]
    (record,) = api.records()
    assert record.operation == "interaction.read"
    assert record.subject is not None
    assert record.subject.target.canonical_id == FINANCE
    assert record.subject.target.entity_type == "domain"
    assert digest_of(record) == purpose_state(ids)


def test_read_many_with_nothing_readable_writes_no_record(api: Api) -> None:
    reader = InteractionContentReader(api.explorer)
    access = api.access(api.scope_of(INVESTIGATOR))
    assert asyncio.run(reader.read_many(access, FINANCE, [new_id()], PURPOSE)) == {}
    assert api.audit.attempts == 0
    assert api.store.content_reads == 0


def test_read_many_is_bounded_and_refuses_malformed_ids(api: Api) -> None:
    reader = InteractionContentReader(api.explorer)
    access = api.access(api.scope_of(INVESTIGATOR))
    with pytest.raises(InvalidSchemaError):
        asyncio.run(reader.read_many(access, FINANCE, [new_id() for _ in range(101)], PURPOSE))
    with pytest.raises(InvalidSchemaError):
        asyncio.run(reader.read_many(access, FINANCE, ["not-a-uuid"], PURPOSE))
    assert api.audit.attempts == 0


def test_read_many_refuses_like_read(api: Api) -> None:
    iid = new_id()
    api.seed(iid)
    reader = InteractionContentReader(api.explorer)
    with pytest.raises(ForbiddenError):
        asyncio.run(reader.read_many(api.access(api.scope_of(VIEWER)), FINANCE, [iid], PURPOSE))
    assert len(api.denials.attempts) == 1
    assert api.store.content_reads == 0


def test_single_read_of_a_missing_id_is_404_from_the_reader(api: Api) -> None:
    reader = InteractionContentReader(api.explorer)
    access = api.access(api.scope_of(INVESTIGATOR))
    with pytest.raises(NotFoundError):
        asyncio.run(reader.read(access, FINANCE, new_id(), PURPOSE))


def test_reader_from_app_state_follows_the_explorer(api: Api, tmp_path: Path) -> None:
    assert isinstance(
        InteractionContentReader.from_app_state(api.h.app.state), InteractionContentReader
    )
    (tmp_path / "off").mkdir()
    off = Api(tmp_path / "off", explorer=False)
    assert InteractionContentReader.from_app_state(off.h.app.state) is None
