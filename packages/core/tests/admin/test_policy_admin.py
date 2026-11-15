"""Policy write repository and pure change functions (PRP-65 item 2), in-memory and a fake Cosmos.

The emulator twin is ``test_policy_admin_cosmos.py`` (``integration``).
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import pytest
from azure.cosmos.exceptions import CosmosBatchOperationError, CosmosResourceNotFoundError
from neurosphere_contracts.admin.v1.domain_membership_change import DomainMembershipChange
from neurosphere_contracts.admin.v1.resource_grant_change import ResourceGrantChange
from neurosphere_contracts.admin.v1.role_assignment_change import RoleAssignmentChange
from neurosphere_core.auth.scope import (
    InMemoryPolicyRepository,
    Permission,
    PolicyHead,
    PolicyRepository,
    Role,
    permits,
    permits_customer_wide,
)
from neurosphere_core.auth.scope.policy_admin import (
    FIRST_POLICY_VERSION,
    CosmosPolicyAdminRepository,
    InMemoryPolicyAdminRepository,
    PolicyAdminRepository,
    apply_grant_change,
    apply_membership_change,
    apply_role_change,
    empty_principal_policy,
    next_policy_version,
    remove_grant,
)
from neurosphere_core.errors import (
    DependencyTransientError,
    ForbiddenError,
    InvalidSchemaError,
    NotFoundError,
    StaleVersionError,
)

from .admin_helpers import (
    CONTROL,
    CUSTOMER,
    FINANCE,
    OPERATIONS,
    OTHER_OBJECT_ID,
    FakeClock,
    at,
    make_claims,
    make_deriver,
    principal_id_for,
    principal_policy,
    role,
)

PID = principal_id_for()
FOREIGN_PID = PID.replace(":contoso:", ":fabrikam:")
AGENT = "commercial:contoso:foundry:agent:support-bot"


def _iso(offset: float) -> str:
    return at(offset).strftime("%Y-%m-%dT%H:%M:%SZ")


def role_change(op: str = "assign", **over: Any) -> RoleAssignmentChange:
    body: dict[str, Any] = {
        "schema_version": "1.0.0",
        "op": op,
        "principal_id": PID,
        "assignment_id": "ra-admin-ops",
        "reason": "access_request",
    }
    if op == "assign":
        body |= {"role": "admin", "domain_ids": [OPERATIONS], "expires_at": _iso(900)}
    body.update(over)
    return RoleAssignmentChange.model_validate(body)


def membership(op: str, domain: str = OPERATIONS, **over: Any) -> DomainMembershipChange:
    body = {
        "schema_version": "1.0.0",
        "op": op,
        "principal_id": PID,
        "domain_id": domain,
        "reason": "access_request",
    } | over
    return DomainMembershipChange.model_validate(body)


def grant_change(**over: Any) -> ResourceGrantChange:
    body = {
        "schema_version": "1.0.0",
        "principal_id": PID,
        "grant_id": "g-1",
        "resource_id": AGENT,
        "permissions": ["read"],
        "expires_at": _iso(1800),
        "reason": "incident_review",
    } | over
    return ResourceGrantChange.model_validate(body)


# ---------------------------------------------------------------------------- versions


@pytest.mark.parametrize(
    ("current", "expected"),
    [
        (None, FIRST_POLICY_VERSION),
        ("local-3", "local-4"),
        ("2026.10.01-1", "2026.10.01-2"),
        ("admin-9", "admin-10"),
        ("v", "v-1"),
        ("none", "none-1"),
    ],
)
def test_next_policy_version_is_monotonic(current: str | None, expected: str) -> None:
    assert next_policy_version(current) == expected
    PolicyHead(customer_id=CUSTOMER, policy_version=expected)  # stays in the head grammar


def test_next_policy_version_refuses_to_overflow() -> None:
    with pytest.raises(InvalidSchemaError):
        next_policy_version("x" * 64)


# ---------------------------------------------------------------------------- pure changes


def test_assign_then_remove_the_last_assignment_leaves_a_valid_document() -> None:
    assigned = apply_role_change(None, role_change(), customer_id=CUSTOMER, now=at(0))
    assert [a.assignment_id for a in assigned.role_assignments] == ["ra-admin-ops"]
    assert assigned.role_assignments[0].role is Role.ADMIN
    assert assigned.role_assignments[0].reason == "access_request"
    removed = apply_role_change(assigned, role_change("remove"), customer_id=CUSTOMER)
    assert removed.role_assignments == ()
    assert removed.id == assigned.id and removed.principal_id == PID
    type(removed).model_validate(removed.model_dump(mode="json"))


def test_assign_replaces_the_same_assignment_id() -> None:
    first = apply_role_change(None, role_change(), customer_id=CUSTOMER, now=at(0))
    again = apply_role_change(
        first,
        role_change(role="viewer", domain_ids=[FINANCE], expires_at=None),
        customer_id=CUSTOMER,
        now=at(0),
    )
    assert len(again.role_assignments) == 1
    assert again.role_assignments[0].role is Role.VIEWER


def test_privileged_assign_without_expiry_is_invalid_schema() -> None:
    with pytest.raises(InvalidSchemaError) as info:
        apply_role_change(None, role_change(expires_at=None), customer_id=CUSTOMER)
    assert info.value.reason == "policy_invalid"


def test_assign_with_past_expiry_is_invalid_schema() -> None:
    with pytest.raises(InvalidSchemaError) as info:
        apply_role_change(None, role_change(expires_at=_iso(-1)), customer_id=CUSTOMER, now=at(0))
    assert info.value.reason == "expiry_in_past"


def test_assign_needs_role_and_domains() -> None:
    change = RoleAssignmentChange.model_validate(
        {
            "schema_version": "1.0.0",
            "op": "assign",
            "principal_id": PID,
            "assignment_id": "ra-x",
            "reason": "access_request",
        }
    )
    with pytest.raises(InvalidSchemaError):
        apply_role_change(None, change, customer_id=CUSTOMER)


def test_remove_of_an_unknown_assignment_is_not_found() -> None:
    with pytest.raises(NotFoundError):
        apply_role_change(None, role_change("remove"), customer_id=CUSTOMER)


@pytest.mark.parametrize(
    "change",
    [
        pytest.param(lambda: role_change(principal_id=FOREIGN_PID), id="foreign-principal"),
        pytest.param(
            lambda: role_change(domain_ids=["commercial:fabrikam:catalog:domain:finance"]),
            id="foreign-domain",
        ),
        pytest.param(
            lambda: role_change(domain_ids=["government:contoso:catalog:domain:finance"]),
            id="foreign-cloud-domain",
        ),
    ],
)
def test_a_change_for_another_customer_or_cloud_raises(change: Any) -> None:
    with pytest.raises(ForbiddenError):
        apply_role_change(None, change(), customer_id=CUSTOMER, now=at(0))


def test_a_change_against_another_principals_document_raises() -> None:
    other = principal_policy(object_id=OTHER_OBJECT_ID)
    with pytest.raises(ForbiddenError):
        apply_role_change(other, role_change(), customer_id=CUSTOMER, now=at(0))


def test_membership_add_is_idempotent_and_remove_is_exact() -> None:
    base = empty_principal_policy(CUSTOMER, PID)
    added = apply_membership_change(base, membership("add"), customer_id=CUSTOMER)
    assert apply_membership_change(added, membership("add"), customer_id=CUSTOMER) == added
    assert added.domain_memberships == (OPERATIONS,)
    removed = apply_membership_change(added, membership("remove"), customer_id=CUSTOMER)
    assert removed.domain_memberships == ()
    with pytest.raises(NotFoundError):
        apply_membership_change(removed, membership("remove"), customer_id=CUSTOMER)
    with pytest.raises(ForbiddenError):
        apply_membership_change(
            base,
            membership("add", domain="commercial:fabrikam:catalog:domain:ops"),
            customer_id=CUSTOMER,
        )


def test_grant_create_replace_and_remove() -> None:
    created = apply_grant_change(None, grant_change(), customer_id=CUSTOMER, now=at(0))
    assert [g.grant_id for g in created.grants] == ["g-1"]
    replaced = apply_grant_change(
        created, grant_change(permissions=["read", "export"]), customer_id=CUSTOMER, now=at(0)
    )
    assert len(replaced.grants) == 1 and replaced.grants[0].permissions == ("read", "export")
    gone = remove_grant(replaced, "g-1", customer_id=CUSTOMER)
    assert gone.grants == ()
    with pytest.raises(NotFoundError):
        remove_grant(gone, "g-1", customer_id=CUSTOMER)


def test_grant_refuses_domains_past_expiry_and_foreign_resources() -> None:
    with pytest.raises(InvalidSchemaError):
        apply_grant_change(None, grant_change(resource_id=FINANCE), customer_id=CUSTOMER)
    with pytest.raises(InvalidSchemaError):
        apply_grant_change(None, grant_change(expires_at=_iso(-5)), customer_id=CUSTOMER, now=at(0))
    with pytest.raises(ForbiddenError):
        apply_grant_change(
            None,
            grant_change(resource_id="commercial:fabrikam:foundry:agent:x"),
            customer_id=CUSTOMER,
        )


def test_invalid_schema_errors_never_echo_values() -> None:
    with pytest.raises(InvalidSchemaError) as info:
        apply_role_change(None, role_change(expires_at=None), customer_id=CUSTOMER)
    rendered = info.value.to_problem_details("corr-1").model_dump_json()
    assert PID not in rendered and OPERATIONS not in rendered


# ---------------------------------------------------------------------------- in-memory repo


def test_twins_satisfy_the_protocols() -> None:
    mem = InMemoryPolicyAdminRepository()
    assert isinstance(mem, PolicyAdminRepository)
    assert isinstance(mem.reader, PolicyRepository)  # read protocol unchanged
    assert isinstance(CosmosPolicyAdminRepository(FakeContainer()), PolicyAdminRepository)  # type: ignore[arg-type]


async def test_create_bumps_the_head_and_replace_needs_the_current_etag() -> None:
    repo = InMemoryPolicyAdminRepository()
    assert await repo.get_with_etag(CUSTOMER, PID) is None
    doc = apply_role_change(None, role_change(), customer_id=CUSTOMER, now=at(0))
    etag = await repo.put_principal_policy(doc, if_match=None)
    head = await repo.reader.get_policy_head(CUSTOMER)
    assert head is not None and head.policy_version == FIRST_POLICY_VERSION

    with pytest.raises(StaleVersionError):  # create-only when the document already exists
        await repo.put_principal_policy(doc, if_match=None)
    stored = await repo.get_with_etag(CUSTOMER, PID)
    assert stored == (doc, etag)

    removed = apply_role_change(doc, role_change("remove"), customer_id=CUSTOMER)
    etag2 = await repo.put_principal_policy(removed, if_match=etag)
    assert etag2 != etag
    head = await repo.reader.get_policy_head(CUSTOMER)
    assert head is not None and head.policy_version == "admin-2"

    with pytest.raises(StaleVersionError) as info:  # the old ETag is now stale
        await repo.put_principal_policy(doc, if_match=etag)
    assert info.value.code == "stale_version"
    head = await repo.reader.get_policy_head(CUSTOMER)
    assert head is not None and head.policy_version == "admin-2"  # nothing written on refusal


async def test_replace_of_a_missing_document_is_stale() -> None:
    repo = InMemoryPolicyAdminRepository()
    with pytest.raises(StaleVersionError):
        await repo.put_principal_policy(empty_principal_policy(CUSTOMER, PID), if_match='"x"')


async def test_list_principals_is_per_customer_and_bounded() -> None:
    reader = InMemoryPolicyRepository()
    reader.put_principal(principal_policy())
    reader.put_principal(principal_policy(object_id=OTHER_OBJECT_ID))
    foreign = empty_principal_policy("fabrikam", FOREIGN_PID)
    reader.put_principal(foreign)
    repo = InMemoryPolicyAdminRepository(reader)
    listed = await repo.list_principals(CUSTOMER)
    assert len(listed) == 2 and all(p.customer_id == CUSTOMER for p in listed)
    assert listed == sorted(listed, key=lambda p: p.id)
    assert len(await repo.list_principals(CUSTOMER, limit=1)) == 1
    with pytest.raises(InvalidSchemaError):
        await repo.list_principals(CUSTOMER, limit=0)


async def test_outage_is_dependency_transient_never_a_write() -> None:
    repo = InMemoryPolicyAdminRepository()
    repo.fail_with(DependencyTransientError("down", reason="policy_store_unavailable"))
    with pytest.raises(DependencyTransientError):
        await repo.put_principal_policy(empty_principal_policy(CUSTOMER, PID), if_match=None)
    repo.fail_with(None)
    assert await repo.reader.get_policy_head(CUSTOMER) is None


async def test_derivation_sees_the_change_after_the_head_bump() -> None:
    """Principal documents are cached by head version: once the cached head ages out, the bumped
    version forces a re-read of the principal document (PRP-06 C14), with no manual flush."""
    repo = InMemoryPolicyAdminRepository()
    clock = FakeClock()
    seed = principal_policy(memberships=(FINANCE, OPERATIONS, CONTROL))
    etag = await repo.put_principal_policy(seed, if_match=None)
    deriver = make_deriver(repo.reader, clock=clock, policy_cache_ttl_seconds=5)

    before = await deriver.from_verified_claims(make_claims())
    assert not permits(before, Permission.CONFIG_MANAGE, domain_id=OPERATIONS, now=at(0))

    granted = apply_role_change(
        seed,
        role_change(domain_ids=[OPERATIONS, CONTROL]),
        customer_id=CUSTOMER,
        now=at(0),
    )
    await repo.put_principal_policy(granted, if_match=etag)
    clock.advance(5)
    after = await deriver.from_verified_claims(make_claims())
    now = clock.datetime()
    assert permits(after, Permission.CONFIG_MANAGE, domain_id=OPERATIONS, now=now)
    assert permits_customer_wide(after, Permission.CONFIG_MANAGE, now=now)
    assert after.policy_version == "admin-2"


async def test_seeded_documents_get_an_etag_on_first_read() -> None:
    reader = InMemoryPolicyRepository()
    reader.put_principal(principal_policy(roles=(role(Role.VIEWER, FINANCE),)))
    repo = InMemoryPolicyAdminRepository(reader)
    found = await repo.get_with_etag(CUSTOMER, PID)
    assert found is not None
    doc, etag = found
    assert await repo.put_principal_policy(doc, if_match=etag)


# ---------------------------------------------------------------------------- Cosmos (fake)


class FakeContainer:
    """The slice of ``ContainerProxy`` the repository uses, with Cosmos batch semantics."""

    def __init__(self) -> None:
        self.items: dict[tuple[str, str], dict[str, Any]] = {}
        self._n = 0
        self.fail: Exception | None = None
        self.batches = 0
        self.head_races = 0  # bump the head before the next N batches (concurrent writer)

    def _etag(self) -> str:
        self._n += 1
        return f'"cos-{self._n}"'

    async def read_item(self, item: str, partition_key: str) -> dict[str, Any]:
        if self.fail is not None:
            raise self.fail
        row = self.items.get((partition_key, item))
        if row is None:
            raise CosmosResourceNotFoundError(message="nf", response=None)
        return dict(row)

    def query_items(self, sql: str, *, parameters: list[dict[str, Any]], partition_key: str):  # type: ignore[no-untyped-def]
        assert "@doc_type" in sql and "@limit" in sql
        values = {p["name"]: p["value"] for p in parameters}
        rows = sorted(
            (r for (pk, _), r in self.items.items() if pk == partition_key),
            key=lambda r: r["id"],
        )
        rows = [r for r in rows if r.get("doc_type") == values["@doc_type"]][: values["@limit"]]

        async def gen():  # type: ignore[no-untyped-def]
            for r in rows:
                yield dict(r)

        return gen()

    async def execute_item_batch(
        self, *, batch_operations: Sequence[Any], partition_key: str
    ) -> list[dict[str, Any]]:
        if self.fail is not None:
            raise self.fail
        self.batches += 1
        if self.head_races:
            self.head_races -= 1
            head = self.items.get((partition_key, "policy-head"))
            if head is not None:
                head["_etag"] = self._etag()
        staged = dict(self.items)
        results: list[dict[str, Any]] = []
        for index, op in enumerate(batch_operations):
            kind, args = op[0], op[1]
            options = op[2] if len(op) > 2 else {}
            body = args[-1]
            key = (partition_key, body["id"])
            current = staged.get(key)
            status = 0
            if kind == "create" and current is not None:
                status = 409
            elif kind == "replace" and current is None:
                status = 404
            elif kind == "replace" and options.get("if_match_etag") != current["_etag"]:  # type: ignore[index]
                status = 412
            if status:
                raise CosmosBatchOperationError(
                    error_index=index,
                    headers={},
                    status_code=status,
                    message="batch failed",
                    operation_responses=[],
                )
            row = dict(body) | {"_etag": self._etag()}
            staged[key] = row
            results.append({"statusCode": 201, "eTag": row["_etag"]})
        self.items = staged
        return results


async def test_cosmos_writes_principal_and_head_in_one_batch() -> None:
    container = FakeContainer()
    repo = CosmosPolicyAdminRepository(container)  # type: ignore[arg-type]
    doc = apply_role_change(None, role_change(), customer_id=CUSTOMER, now=at(0))
    etag = await repo.put_principal_policy(doc, if_match=None)
    assert container.batches == 1
    assert container.items[(CUSTOMER, "policy-head")]["policy_version"] == FIRST_POLICY_VERSION
    found = await repo.get_with_etag(CUSTOMER, PID)
    assert found == (doc, etag)

    removed = apply_role_change(doc, role_change("remove"), customer_id=CUSTOMER)
    await repo.put_principal_policy(removed, if_match=etag)
    assert container.items[(CUSTOMER, "policy-head")]["policy_version"] == "admin-2"
    with pytest.raises(StaleVersionError):
        await repo.put_principal_policy(doc, if_match=etag)
    with pytest.raises(StaleVersionError):
        await repo.put_principal_policy(doc, if_match=None)
    assert container.items[(CUSTOMER, "policy-head")]["policy_version"] == "admin-2"
    listed = await repo.list_principals(CUSTOMER)
    assert [p.principal_id for p in listed] == [PID]


async def test_cosmos_retries_a_head_race_but_not_forever() -> None:
    container = FakeContainer()
    repo = CosmosPolicyAdminRepository(container)  # type: ignore[arg-type]
    first = await repo.put_principal_policy(empty_principal_policy(CUSTOMER, PID), if_match=None)
    container.head_races = 1
    other = principal_policy(object_id=OTHER_OBJECT_ID, memberships=())
    assert await repo.put_principal_policy(other, if_match=None)
    assert container.items[(CUSTOMER, "policy-head")]["policy_version"] == "admin-2"
    container.head_races = 10
    with pytest.raises(StaleVersionError) as info:
        await repo.put_principal_policy(empty_principal_policy(CUSTOMER, PID), if_match=first)
    assert info.value.reason == "policy_head_contended"


async def test_cosmos_failures_map_to_dependency_transient() -> None:
    container = FakeContainer()
    repo = CosmosPolicyAdminRepository(container)  # type: ignore[arg-type]
    container.fail = RuntimeError("socket closed: secret-ish detail")
    with pytest.raises(DependencyTransientError) as info:
        await repo.put_principal_policy(empty_principal_policy(CUSTOMER, PID), if_match=None)
    assert "socket" not in str(info.value)
    with pytest.raises(DependencyTransientError):
        await repo.get_with_etag(CUSTOMER, PID)


async def test_cosmos_malformed_document_is_upstream_invalid() -> None:
    container = FakeContainer()
    container.items[(CUSTOMER, "principal.p-x")] = {"id": "principal.p-x", "_etag": '"1"'}
    repo = CosmosPolicyAdminRepository(container)  # type: ignore[arg-type]
    with pytest.raises(DependencyTransientError) as info:
        await repo.get_with_etag(CUSTOMER, "commercial:contoso:entra:person:p-x")
    assert info.value.status == 502
