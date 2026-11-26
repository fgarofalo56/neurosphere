"""ABAC negative suite for the governance policy routes (PRP-105 item 7, criterion 8).

The suite world serves the real router table, so ``/api/v1/governance/policy`` is mounted;
``security.governance_policy.govpolicy_world`` installs the governance plane (stores shared by
both customers, like one Cosmos account) and the action plane (no write connector) on each
deployment. Every one of the 13 operations gets a deny case per dimension, none skipped:

=========================  ===================================================================
Dimension                  Expected refusal
=========================  ===================================================================
no role                    403, denial recorded, nothing written (a member with no assignment)
permission missing         403 for a role without the route's permission: investigator for
                           reads; viewer, analyst, auditor for manage routes; viewer, admin,
                           auditor for exception requests (``action.propose``)
wrong domain               403 ``target_out_of_scope`` naming the path domain (operations
                           steward on a finance path); ``/status`` never lists that domain
wrong customer             401 for another tenant's token; 403 for a domain of another
                           customer; ``/status`` never lists another customer's domain
wrong cloud                403 for a Government domain on a Commercial deployment; ``/status``
                           lists Commercial domains only
expired assignment         403 ``permission_missing`` once the steward assignment lapsed
=========================  ===================================================================

Out-of-scope ids (another domain, another customer, another cloud) answer 404 with a body
identical to a missing id's once the requested id itself is masked. Customer-wide policies live
in the customer-control domain and need the permission there. Exception requests need
``action.propose`` in the violation's domain; the requester cannot review their own request.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Final

import pytest
from neurosphere_core.auth.scope import Role, customer_control_domain_id
from neurosphere_core.errors import ForbiddenError
from neurosphere_core.governance.policy import ExceptionFilters, ViolationFilters
from neurosphere_core.paging import PageRequest

from ..governance_policy.govpolicy_world import (
    EXPIRES_IN,
    Extra,
    GovDep,
    GovWorld,
    agent,
    draft_body,
    extra_pid,
    install,
)
from .world import CUSTOMERS, DOMAINS, Who, World, build_world, domain_id, run

FIN: Final = "finance"
OPS: Final = "operations"
POLICY_ID: Final = "fin-owners"
MISSING_POLICY: Final = "no-such-policy"
MISSING_VIOLATION: Final = "00000000-0000-4000-8000-00000000dead"
GOV_POLICY: Final = "gov-owners"
#: Key of the Government-cloud violation in ``Seeded.violation_ids``.
GOVERNMENT: Final = "contoso-government"


@dataclass
class Seeded:
    gw: GovWorld
    violation_ids: dict[str, str]
    etags: dict[str, str]

    def __getitem__(self, customer: str) -> GovDep:
        return self.gw[customer]


def _policy_id(customer: str) -> str:
    return POLICY_ID if customer == "contoso" else "fab-owners"


def _seed(world: World) -> Seeded:
    gw = install(world)
    violation_ids: dict[str, str] = {}
    etags: dict[str, str] = {}
    for customer in CUSTOMERS:
        gd = gw[customer]
        steward = gd.dep.bearer(Who(customer, FIN, Role.DOMAIN_STEWARD))
        created = gd.call(
            "POST",
            f"/domains/{gd.domain(FIN)}/policies",
            steward,
            json=draft_body(_policy_id(customer)),
        )
        assert created.status_code == 201, created.text
        etags[customer] = created.json()["etag"]
        stored = run(
            gd.violation(
                domain=gd.domain(FIN),
                subject=agent(customer, "support-bot"),
                policy_id=_policy_id(customer),
            )
        )
        violation_ids[customer] = stored.violation.violation_id.root
        for name in DOMAINS:
            run(gd.run_status(gd.domain(name)))
    # A Government-cloud draft of the same customer: never visible on Commercial.
    gov = gw["contoso"]
    run(
        gov.plane.policies.create_draft(
            {
                **draft_body(GOV_POLICY),
                "schema_version": "1.2.0",
                "policy_version": 1,
                "previous_version": None,
                "cloud": "government",
                "customer_id": "contoso",
                "domain_id": domain_id("contoso", FIN, "government"),
                "document_url": None,
                "status": "draft",
                "created_by": extra_pid("contoso", Extra.CONTROL).replace(
                    "commercial:", "government:", 1
                ),
                "created_at": "2027-01-15T08:00:00Z",
                "published_at": None,
                "published_intent_id": None,
                "published_audit_id": None,
            }
        )
    )
    gov_violation = run(
        gov.violation(
            domain=domain_id("contoso", FIN, "government"),
            subject="government:contoso:foundry:agent:support-bot",
            policy_id=GOV_POLICY,
            cloud="government",
        )
    )
    violation_ids[GOVERNMENT] = gov_violation.violation.violation_id.root
    return Seeded(gw=gw, violation_ids=violation_ids, etags=etags)


@pytest.fixture(scope="module")
def seeded() -> Seeded:
    """Read-only for the deny cases: every one asserts that it wrote nothing."""
    return _seed(build_world())


@pytest.fixture(scope="module")
def lapsed() -> Seeded:
    """The steward assignment works, then lapses (the clock moves past its expiry)."""
    seeded = _seed(build_world())
    gd = seeded["contoso"]
    live = _call(gd, ROUTES[0], gd.bearer_extra(Extra.EXPIRED))
    assert live.status_code == 200, "the assignment must work before it lapses"
    seeded.gw.world.clock.advance(EXPIRES_IN + 1)
    return seeded


@pytest.fixture(scope="module")
def allowed() -> Seeded:
    """The positive control's own world (its calls write)."""
    return _seed(build_world())


@pytest.fixture
def fresh(world: World) -> Seeded:
    return _seed(world)


# -- routes ---------------------------------------------------------------------------------


Need = str  # "read" | "manage" | "propose" | "status"


def _draft_put_body(_gd: GovDep) -> dict[str, Any]:
    return {k: v for k, v in draft_body().items() if k != "policy_id"}


def _stage_body(_gd: GovDep) -> dict[str, Any]:
    return {"version": 1, "idempotency_key": "govpolicy-suite-0001"}


def _exception_body(gd: GovDep) -> dict[str, Any]:
    return {
        "justification_code": "migration_in_progress",
        "justification_text": "Owner hand-over is scheduled.",
        "expires_at": gd.expiry(10),
    }


def _no_body(_gd: GovDep) -> None:
    return None


def _create_body(_gd: GovDep) -> dict[str, Any]:
    return draft_body("new-policy")


@dataclass(frozen=True)
class Route:
    name: str
    method: str
    template: str  # {d} domain, {p} policy id, {v} violation id; "" = no domain
    need: Need
    body: Callable[[GovDep], Any]

    def path(self, domain: str, policy_id: str = POLICY_ID, violation_id: str = "") -> str:
        return self.template.format(d=domain, p=policy_id, v=violation_id)

    @property
    def has_domain(self) -> bool:
        return "{d}" in self.template

    @property
    def has_id(self) -> bool:
        return "{p}" in self.template or "{v}" in self.template


ROUTES: Final[tuple[Route, ...]] = (
    Route("policy-list", "GET", "/domains/{d}/policies", "read", _no_body),
    Route("policy-create", "POST", "/domains/{d}/policies", "manage", _create_body),
    Route("policy-get", "GET", "/domains/{d}/policies/{p}", "read", _no_body),
    Route("policy-versions", "GET", "/domains/{d}/policies/{p}/versions", "read", _no_body),
    Route("policy-draft-put", "PUT", "/domains/{d}/policies/{p}/draft", "manage", _draft_put_body),
    Route("policy-publish", "POST", "/domains/{d}/policies/{p}/publish", "manage", _stage_body),
    Route("policy-retire", "POST", "/domains/{d}/policies/{p}/retire", "manage", _stage_body),
    Route("violation-list", "GET", "/domains/{d}/violations", "read", _no_body),
    Route("violation-get", "GET", "/domains/{d}/violations/{v}", "read", _no_body),
    Route(
        "exception-request",
        "POST",
        "/domains/{d}/violations/{v}/exception-requests",
        "propose",
        _exception_body,
    ),
    Route("exception-list", "GET", "/domains/{d}/exceptions", "read", _no_body),
    Route("binding-list", "GET", "/domains/{d}/bindings", "read", _no_body),
    Route("status", "GET", "/status", "status", _no_body),
)
DOMAIN_ROUTES: Final = tuple(r for r in ROUTES if r.has_domain)
ID_ROUTES: Final = tuple(r for r in ROUTES if r.has_id)

#: Roles of the world that lack each route's permission in the domain they hold.
LACKING: Final[dict[Need, tuple[Role, ...]]] = {
    "read": (Role.INTERACTION_INVESTIGATOR,),
    "status": (Role.INTERACTION_INVESTIGATOR,),
    "manage": (Role.VIEWER, Role.ANALYST, Role.SECURITY_AUDITOR),
    "propose": (Role.VIEWER, Role.ADMIN, Role.SECURITY_AUDITOR),
}
LACKING_CASES: Final = tuple((route, role) for route in ROUTES for role in LACKING[route.need])


def _call(
    gd: GovDep,
    route: Route,
    headers: dict[str, str],
    *,
    domain: str | None = None,
    policy_id: str = POLICY_ID,
    violation_id: str | None = None,
) -> Any:
    target = domain if domain is not None else gd.domain(FIN)
    vid = violation_id if violation_id is not None else MISSING_VIOLATION
    path = route.path(target, policy_id, vid)
    extra = {"If-Match": '"suite-etag"'} if route.method == "PUT" else {}
    return gd.call(route.method, path, {**headers, **extra}, json=route.body(gd))


def _headers_for(gd: GovDep, role: Role) -> dict[str, str]:
    if role is Role.INTERACTION_INVESTIGATOR:
        return gd.bearer_extra(Extra.INVESTIGATOR)
    return gd.dep.bearer(Who(gd.customer, FIN, role))


async def _state_of(seeded: Seeded) -> tuple[Any, ...]:
    """Everything a refused call could have written, for every customer."""
    stores = seeded.gw.stores
    out: list[Any] = []
    for customer in CUSTOMERS:
        gd = seeded[customer]
        domains = tuple(
            [
                *(domain_id(customer, d) for d in DOMAINS),
                customer_control_domain_id("commercial", customer),
            ]
        )
        page = PageRequest(page_size=100)
        policies = await stores.policies.list(customer, domains, page)
        violations = await stores.violations.list(customer, ViolationFilters(domains), page)
        exceptions = await stores.exceptions.list(customer, ExceptionFilters(domains), page)
        bindings = await stores.bindings.list(customer, include_retired=True)
        tail = await gd.dep.audit_repo.tail(f"{customer}.governance-policy")
        out.append(
            (
                sorted(
                    (s.policy.policy_id.root, s.policy.policy_version, s.etag)
                    for s in policies.items
                ),
                sorted(s.etag for s in violations.items),
                sorted(s.etag for s in exceptions.items),
                sorted(s.etag for s in bindings),
                gd.intents.create_calls + gd.intents.replace_calls,
                None if tail is None else tail.sequence,
            )
        )
    return tuple(out)


def _state(seeded: Seeded) -> tuple[Any, ...]:
    return run(_state_of(seeded))


def _assert_refused(
    seeded: Seeded,
    gd: GovDep,
    route: Route,
    headers: dict[str, str],
    *,
    status: int = 403,
    reason: str | None = None,
    recorded: bool = True,
    **where: Any,
) -> Any:
    before = _state(seeded)
    attempts = len(gd.dep.recorder.attempts)
    response = _call(gd, route, headers, **where)
    assert response.status_code == status, f"{route.name}: {response.status_code} {response.text}"
    if reason is not None:
        assert response.json()["reason"] == reason, response.text
    if recorded:
        assert len(gd.dep.recorder.attempts) == attempts + 1, "no denial was recorded"
    assert _state(seeded) == before, f"{route.name}: a refused call wrote something"
    return response


# -- dimension 1: no role ---------------------------------------------------------------------


@pytest.mark.parametrize("route", ROUTES, ids=lambda r: r.name)
def test_no_role_is_denied(seeded: Seeded, route: Route) -> None:
    gd = seeded["contoso"]
    _assert_refused(
        seeded,
        gd,
        route,
        gd.bearer_extra(Extra.NO_ROLE),
        violation_id=seeded.violation_ids["contoso"],
    )


# -- dimension 2: a role without the route's permission --------------------------------------


@pytest.mark.parametrize(
    ("route", "role"),
    LACKING_CASES,
    ids=[f"{r.name}-{role.value}" for r, role in LACKING_CASES],
)
def test_role_without_the_permission_is_denied(seeded: Seeded, route: Route, role: Role) -> None:
    gd = seeded["contoso"]
    _assert_refused(
        seeded, gd, route, _headers_for(gd, role), violation_id=seeded.violation_ids["contoso"]
    )


# -- dimension 3: wrong domain ------------------------------------------------------------------


@pytest.mark.parametrize("route", ROUTES, ids=lambda r: r.name)
def test_wrong_domain_is_denied(seeded: Seeded, route: Route) -> None:
    gd = seeded["contoso"]
    headers = gd.dep.bearer(Who("contoso", OPS, Role.DOMAIN_STEWARD))
    if not route.has_domain:
        response = _call(gd, route, headers)
        assert response.status_code == 200, response.text
        runs = [r["domain_id"] for r in response.json()["runs"]]
        assert runs == [gd.domain(OPS)], "a domain outside the scope was described"
        return
    _assert_refused(
        seeded,
        gd,
        route,
        headers,
        reason="target_out_of_scope",
        violation_id=seeded.violation_ids["contoso"],
    )
    assert gd.dep.recorder.attempts[-1].domain_id == gd.domain(FIN)


# -- dimension 4: wrong customer ----------------------------------------------------------------


@pytest.mark.parametrize("route", ROUTES, ids=lambda r: r.name)
def test_another_customers_token_is_not_accepted(seeded: Seeded, route: Route) -> None:
    gd = seeded["contoso"]
    foreign = gd.bearer_extra(Extra.CONTROL, customer="fabrikam")
    _assert_refused(seeded, gd, route, foreign, status=401, recorded=False)
    world_foreign = seeded["fabrikam"].dep.bearer(Who("fabrikam", FIN, Role.DOMAIN_STEWARD))
    _assert_refused(seeded, gd, route, world_foreign, status=401, recorded=False)


@pytest.mark.parametrize("route", ROUTES, ids=lambda r: r.name)
def test_another_customers_domain_is_denied(seeded: Seeded, route: Route) -> None:
    gd = seeded["contoso"]
    headers = gd.dep.bearer(Who("contoso", FIN, Role.DOMAIN_STEWARD))
    if not route.has_domain:
        response = _call(gd, route, headers)
        assert response.status_code == 200, response.text
        assert all(r["domain_id"].split(":")[1] == "contoso" for r in response.json()["runs"])
        assert "fabrikam" not in response.text
        return
    _assert_refused(
        seeded,
        gd,
        route,
        headers,
        domain=domain_id("fabrikam", FIN),
        policy_id=_policy_id("fabrikam"),
        violation_id=seeded.violation_ids["fabrikam"],
    )


# -- dimension 5: wrong cloud -------------------------------------------------------------------


@pytest.mark.parametrize("route", ROUTES, ids=lambda r: r.name)
def test_another_clouds_domain_is_denied(seeded: Seeded, route: Route) -> None:
    gd = seeded["contoso"]
    headers = gd.dep.bearer(Who("contoso", FIN, Role.DOMAIN_STEWARD))
    if not route.has_domain:
        response = _call(gd, route, headers)
        assert response.status_code == 200, response.text
        assert {r["domain_id"].split(":")[0] for r in response.json()["runs"]} == {"commercial"}
        return
    _assert_refused(
        seeded,
        gd,
        route,
        headers,
        domain=domain_id("contoso", FIN, "government"),
        policy_id=GOV_POLICY,
        violation_id=seeded.violation_ids["contoso"],
    )


# -- dimension 6: expired assignment ------------------------------------------------------------


@pytest.mark.parametrize("route", ROUTES, ids=lambda r: r.name)
def test_expired_assignment_is_denied(lapsed: Seeded, route: Route) -> None:
    gd = lapsed["contoso"]
    _assert_refused(
        lapsed,
        gd,
        route,
        gd.bearer_extra(Extra.EXPIRED),
        reason="target_out_of_scope" if route.has_domain else "permission_missing",
        violation_id=lapsed.violation_ids["contoso"],
    )


# -- no token, and the positive control ---------------------------------------------------------


@pytest.mark.parametrize("route", ROUTES, ids=lambda r: r.name)
def test_no_token_is_401(seeded: Seeded, route: Route) -> None:
    _assert_refused(seeded, seeded["contoso"], route, {}, status=401, recorded=False)


@pytest.mark.parametrize("route", ROUTES, ids=lambda r: r.name)
def test_an_in_scope_holder_reaches_the_route(allowed: Seeded, route: Route) -> None:
    """The deny cases are not vacuous: the right role in the right domain gets through."""
    gd = allowed["contoso"]
    role = Role.ANALYST if route.need == "propose" else Role.DOMAIN_STEWARD
    response = _call(
        gd,
        route,
        gd.dep.bearer(Who("contoso", FIN, role)),
        violation_id=allowed.violation_ids["contoso"],
    )
    assert response.status_code not in (401, 403, 404), f"{route.name}: {response.text}"


# -- out-of-scope ids are 404, indistinguishable from missing ----------------------------------


def _masked(response: Any, *ids: str) -> str:
    """The full problem body with the per-request correlation id and the asked-for ids masked."""
    body = dict(response.json())
    assert isinstance(body.pop("correlation_id", None), str)
    text = json.dumps(body, sort_keys=True)
    for value in ids:
        text = text.replace(value, "<id>")
    return text


def _assert_like_missing(
    gd: GovDep, route: Route, headers: dict[str, str], *, domain: str, hidden: tuple[str, str]
) -> None:
    hidden_policy, hidden_violation = hidden
    seen = _call(
        gd, route, headers, domain=domain, policy_id=hidden_policy, violation_id=hidden_violation
    )
    missing = _call(
        gd,
        route,
        headers,
        domain=domain,
        policy_id=MISSING_POLICY,
        violation_id=MISSING_VIOLATION,
    )
    assert seen.status_code == missing.status_code == 404, f"{route.name}: {seen.text}"
    assert _masked(seen, hidden_policy, hidden_violation) == _masked(
        missing, MISSING_POLICY, MISSING_VIOLATION
    ), f"{route.name}: an out-of-scope id is distinguishable from a missing one"


@pytest.mark.parametrize("route", ID_ROUTES, ids=lambda r: r.name)
def test_an_id_in_another_domain_is_404_like_a_missing_one(seeded: Seeded, route: Route) -> None:
    gd = seeded["contoso"]
    headers = gd.dep.bearer(Who("contoso", OPS, Role.DOMAIN_STEWARD))
    before = _state(seeded)
    _assert_like_missing(
        gd,
        route,
        headers,
        domain=gd.domain(OPS),
        hidden=(POLICY_ID, seeded.violation_ids["contoso"]),
    )
    assert _state(seeded) == before


@pytest.mark.parametrize("route", ID_ROUTES, ids=lambda r: r.name)
def test_an_id_of_another_customer_is_404_like_a_missing_one(seeded: Seeded, route: Route) -> None:
    gd = seeded["fabrikam"]
    headers = gd.dep.bearer(Who("fabrikam", FIN, Role.DOMAIN_STEWARD))
    if route.need == "propose":
        headers = gd.dep.bearer(Who("fabrikam", FIN, Role.ANALYST))
    before = _state(seeded)
    _assert_like_missing(
        gd,
        route,
        headers,
        domain=gd.domain(FIN),
        hidden=(POLICY_ID, seeded.violation_ids["contoso"]),
    )
    assert _state(seeded) == before


@pytest.mark.parametrize("route", ID_ROUTES, ids=lambda r: r.name)
def test_an_id_of_another_cloud_is_404_like_a_missing_one(seeded: Seeded, route: Route) -> None:
    gd = seeded["contoso"]
    headers = gd.dep.bearer(Who("contoso", FIN, Role.DOMAIN_STEWARD))
    if route.need == "propose":
        headers = gd.dep.bearer(Who("contoso", FIN, Role.ANALYST))
    _assert_like_missing(
        gd,
        route,
        headers,
        domain=gd.domain(FIN),
        hidden=(GOV_POLICY, seeded.violation_ids[GOVERNMENT]),
    )


def test_lists_never_carry_another_domain_customer_or_cloud(seeded: Seeded) -> None:
    for customer in CUSTOMERS:
        gd = seeded[customer]
        for name in DOMAINS:
            headers = gd.dep.bearer(Who(customer, name, Role.DOMAIN_STEWARD))
            for route in (r for r in DOMAIN_ROUTES if r.method == "GET" and not r.has_id):
                response = _call(gd, route, headers, domain=gd.domain(name))
                assert response.status_code == 200, response.text
                for item in response.json()["items"]:
                    record = next(
                        v for k, v in item.items() if isinstance(v, dict) and k != "capability"
                    )
                    assert record["domain_id"] == gd.domain(name), route.name
                    assert record["customer_id"] == customer
                    assert record["cloud"] == "commercial"
        listed = gd.call(
            "GET",
            f"/domains/{gd.domain(FIN)}/policies",
            gd.dep.bearer(Who(customer, FIN, Role.VIEWER)),
        )
        ids = [p["policy"]["policy_id"] for p in listed.json()["items"]]
        assert ids == [_policy_id(customer)]


# -- customer-wide policies ---------------------------------------------------------------------


def test_customer_wide_policies_need_the_permission_in_the_control_domain(
    fresh: Seeded,
) -> None:
    gd = fresh["contoso"]
    control = customer_control_domain_id("commercial", "contoso")
    control_steward = gd.bearer_extra(Extra.CONTROL)
    created = gd.call(
        "POST", f"/domains/{control}/policies", control_steward, json=draft_body("customer-owners")
    )
    assert created.status_code == 201, created.text
    for role in (Role.DOMAIN_STEWARD, Role.ADMIN, Role.VIEWER):
        headers = gd.dep.bearer(Who("contoso", FIN, role))
        for route in DOMAIN_ROUTES:
            response = _call(gd, route, headers, domain=control, policy_id="customer-owners")
            assert response.status_code == 403, f"{route.name} {role.value}: {response.text}"
        # Through its own domain the customer-wide id is 404 like a missing one.
        hidden = gd.call("GET", f"/domains/{gd.domain(FIN)}/policies/customer-owners", headers)
        assert hidden.status_code == 404
    read = gd.call("GET", f"/domains/{control}/policies/customer-owners", control_steward)
    assert read.status_code == 200, read.text


# -- exception requests -------------------------------------------------------------------------


def test_an_exception_request_needs_action_propose_in_the_violations_domain(
    fresh: Seeded,
) -> None:
    gd = fresh["contoso"]
    route = next(r for r in ROUTES if r.name == "exception-request")
    vid = fresh.violation_ids["contoso"]
    # action.propose held in ANOTHER domain does not reach this violation.
    other = gd.dep.bearer(Who("contoso", OPS, Role.ANALYST))
    refused = _call(gd, route, other, violation_id=vid)
    assert refused.status_code == 403, refused.text
    granted = _call(gd, route, gd.dep.bearer(Who("contoso", FIN, Role.ANALYST)), violation_id=vid)
    assert granted.status_code == 201, granted.text


def test_the_requester_cannot_review_their_own_exception(fresh: Seeded) -> None:
    gd = fresh["contoso"]
    route = next(r for r in ROUTES if r.name == "exception-request")
    steward = Who("contoso", FIN, Role.DOMAIN_STEWARD)
    scope = gd.scope_of(steward)
    principal = scope.to_contract().principal.principal_id.root
    for permission in ("action.propose", "action.approve", "catalog.curate"):
        gd.rechecker.grant(principal, "contoso", gd.domain(FIN), permission)
    view = _call(gd, route, gd.dep.bearer(steward), violation_id=fresh.violation_ids["contoso"])
    assert view.status_code == 201, view.text
    item_id = view.json()["review_item_id"]
    item = run(gd.hitl.get(item_id))
    assert item is not None and item.maker is not None
    maker = item.maker
    with pytest.raises(ForbiddenError) as refused:
        run(
            gd.hitl.decide(
                item_id,
                principal,
                maker,
                "approved",
                "self approval attempt",
                None,
                gd.now(),
                "corr-self-review",
                scope_hash=scope.scope_hash,
            )
        )
    assert refused.value.reason == "self_approval_forbidden"
    still = run(gd.hitl.get(item_id))
    assert still is not None and still.state == item.state


def test_a_taken_policy_id_elsewhere_is_409_and_names_nothing_about_it(fresh: Seeded) -> None:
    """Policy ids are unique per customer, so a create that collides with an id in a domain
    the caller cannot see answers 409 ``policy_exists`` (by design, service.py). The answer
    must not say where the policy lives or what it is, and nothing is written."""
    gd = fresh["contoso"]
    route = next(r for r in ROUTES if r.name == "policy-create")
    headers = gd.dep.bearer(Who("contoso", OPS, Role.DOMAIN_STEWARD))
    before = _state(fresh)
    response = gd.call(
        route.method, route.path(gd.domain(OPS)), headers, json=draft_body(POLICY_ID)
    )
    assert response.status_code == 409, response.text
    assert response.json()["reason"] == "policy_exists"
    for leak in (gd.domain(FIN), "Finance owners", fresh.etags["contoso"], "finance"):
        assert leak not in response.text
    assert _state(fresh)[0][:4] == before[0][:4], "the colliding create wrote nothing"
