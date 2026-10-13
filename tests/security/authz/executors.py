"""Case executors: one function per path kind, shared by the per-path and privileged tests."""

from typing import NamedTuple

import pytest
from neurosphere_api.authz import cache_key_prefix, scope_cache_key
from neurosphere_core.auth.revocation import PushSessionRegistry, RevocationHookRegistry
from neurosphere_core.auth.scope import Permission, permits
from neurosphere_core.errors import ForbiddenError, NeuroSphereError
from neurosphere_core.scope import IdentityScope
from pydantic import ValidationError

from .cases import (
    ADMIN_C_FIN,
    AUDITOR_C_FIN,
    AUDITOR_C_OPS,
    C_FIN_1,
    C_OPS_1,
    GRANT_EXPIRES_IN,
    READ_ROLES,
    ApiCase,
    ExportCase,
    Kind,
    ScenarioCase,
    SearchCase,
    can_read,
    domain_items,
    privileged_grants,
)
from .support import AuditProbe, Ledger
from .world import (
    ALL_PRINCIPALS,
    AUDIENCE,
    REVOCATION_TTL,
    T0,
    TENANTS,
    Deployment,
    FakePushRegistry,
    ScopeKeyedCache,
    Who,
    World,
    build_world,
    dev_issuer,
    domain_id,
    item_domain,
    principal_id_for,
    run,
)

LIFECYCLE_SCENARIOS = (
    "revoked-after-ttl",
    "revoked-with-fanout",
    "policy-outage",
    "policy-outage-after-cache-ttl",
    "revocation-outage",
)
POLICY_CACHE_MAX_TTL = 301.0


# ------------------------------------------------------------------------------------ API


def _auth_headers(world: World, case: ApiCase) -> dict[str, str]:
    issuer_dep = world[case.who.customer]
    mode = case.auth
    if mode == "own":
        return issuer_dep.bearer(case.who, **case.claims)
    if mode == "none":
        return {}
    if mode == "garbage":
        return {"Authorization": "Bearer garbage"}
    if mode == "scheme":
        return {"Authorization": "Basic abc"}
    if mode == "expired":
        return issuer_dep.bearer(case.who, exp=int(T0) - 10)
    if mode == "wrong_audience":
        return issuer_dep.bearer(case.who, aud="api://other")
    if mode == "wrong_key":
        customer = case.who.customer
        claims = {
            "iss": dev_issuer(customer).issuer,
            "aud": AUDIENCE,
            "tid": TENANTS[customer],
            "oid": case.who.object_id,
            "sub": "forged",
            "ver": "2.0",
            "iat": int(T0),
            "nbf": int(T0),
            "exp": int(T0) + 3000,
        }
        other = next(c for c in TENANTS if c != customer)
        return {"Authorization": "Bearer " + dev_issuer(other).sign(claims)}
    raise AssertionError(f"unknown auth mode {mode}")


def run_api_case(world: World, case: ApiCase) -> None:
    assert case.why.strip(), "every row needs a reason entry"
    assert case.audit != "none" or case.gap.strip(), "an audit gap needs a stated reason"
    dep = world[case.app]
    headers = {**_auth_headers(world, case), **case.headers}
    probe = AuditProbe(dep)
    response = dep.client.request(
        case.method,
        case.path,
        headers=headers,
        params=dict(case.params) or None,
        json=case.body,
    )
    assert response.status_code == case.status, response.text
    body = response.json()
    if case.status == 200:
        if case.items is not None:
            assert set(body["items"]) == case.items
            assert not set(body["items"]) - case.items, "leaked items"
    else:
        assert body.get("reason") == case.reason
        assert "items" not in body, "denied response must not carry data"
    probe.assert_decision(case.audit, who=case.who, reason=case.reason)


# ---------------------------------------------------------------------------------- search


def run_search_case(world: World, case: SearchCase) -> None:
    assert case.why.strip()
    dep = world[case.who.customer]
    if case.advance:
        world.clock.advance(case.advance)
    scope = dep.scope(case.who)
    ledger = Ledger(world)
    if case.refused:
        with pytest.raises(ValidationError):
            run(dep.search.search(scope, "triage", case.raw_filters))
        ledger.note(dep, "denied", case.decision)
        ledger.verify()
        return
    result, decision = run(dep.search.search(scope, "triage", case.raw_filters))
    hits = {h.id for h in result.hits}
    assert decision == case.decision
    assert hits == case.expected_ids
    # Independent leak invariant straight from the scope object (not from the oracle).
    contract = scope.to_contract()
    granted = {g.resource_id.root for g in contract.allowed_resources if "read" in g.permissions}
    for hit in hits:
        assert hit.split(":")[1] == scope.customer_id, "cross-customer hit"
        assert item_domain(hit) in scope.allowed_domains or hit in granted, "out-of-scope hit"
    if decision == "allow":
        ledger.note(dep, "allow")
    else:
        ledger.note(dep, "denied", decision)
    ledger.verify()


# ---------------------------------------------------------------------------------- export


def audited_export(
    dep: Deployment,
    scope: IdentityScope,
    ledger: Ledger,
    *,
    domain: str | None,
    resource: str | None,
) -> list[str]:
    """Direct (non-HTTP) export caller: same function and scope object, decision audited."""
    try:
        rows = dep.exporter.export(scope, domain_id=domain, resource_id=resource)
    except ForbiddenError as exc:
        run(
            dep.audit.deny(
                scope,
                "data.export",
                exc.reason or "forbidden",
                target=resource or domain,
                domain=domain,
            )
        )
        ledger.note(dep, "denied", exc.reason)
        raise
    run(dep.audit.allow(scope, "data.export", target=resource or domain, domain=domain))
    ledger.note(dep, "allow")
    return rows


def run_export_case(world: World, case: ExportCase) -> None:
    assert case.why.strip()
    dep = world[case.who.customer]
    body: dict[str, str] = {}
    if case.target_domain:
        body["domain_id"] = case.target_domain
    if case.target_resource:
        body["resource_id"] = case.target_resource

    probe = AuditProbe(dep)
    response = dep.client.post("/d/export", json=body, headers=dep.bearer(case.who))
    assert response.status_code == case.status, response.text
    payload = response.json()
    if case.status == 200:
        assert set(payload["items"]) == case.items
    else:
        assert payload.get("reason") == case.http_reason
        assert "items" not in payload
    probe.assert_decision(case.audit, who=case.who, reason=case.http_reason)

    # Same scope object straight into the export function.
    scope = dep.scope(case.who)
    ledger = Ledger(world)
    if case.status == 200:
        rows = audited_export(
            dep, scope, ledger, domain=case.target_domain, resource=case.target_resource
        )
        assert set(rows) == case.items
        for row in rows:
            assert permits(
                scope,
                Permission.DATA_EXPORT,
                now=world.clock.dt(),
                domain_id=item_domain(row),
                resource_id=row,
            )
    else:
        with pytest.raises(ForbiddenError) as raised:
            audited_export(
                dep, scope, ledger, domain=case.target_domain, resource=case.target_resource
            )
        assert raised.value.reason == case.direct_reason
    ledger.verify()


# ------------------------------------------------------------------------------ lifecycle


class Outcome(NamedTuple):
    status: int
    reason: str | None


def attempt(dep: Deployment, kind: Kind, who: Who, token: str) -> Outcome:
    """Try to use one path with ``token``; (200, None) when the path served the request."""
    if kind == "api":
        response = dep.client.get("/d/items", headers={"Authorization": f"Bearer {token}"})
        if response.status_code == 200:
            return Outcome(200, None)
        return Outcome(response.status_code, response.json().get("reason"))
    try:
        scope = run(dep.derive_token(token)).scope
        if kind == "search":
            run(dep.search.search(scope, "triage"))
        elif kind == "export":
            dep.exporter.export(scope, domain_id=who.domain_id)
        elif kind == "cache":
            dep.cache.get_view(scope)
        else:
            dep.push.connect(scope, who.domain_id)
    except NeuroSphereError as exc:
        return Outcome(exc.status, exc.reason)
    return Outcome(200, None)


def run_lifecycle(kind: Kind, row: ScenarioCase) -> None:
    assert row.who is not None
    victim = row.who
    scenario = row.scenario
    world = build_world()
    dep = world[victim.customer]
    admin = ADMIN_C_FIN
    assert victim != admin
    if scenario == "revoked-after-ttl":
        token = dep.token(victim)
        assert attempt(dep, kind, victim, token) == (200, None)  # warms every cache
        dep.revoke(admin, victim, hooks=False)  # written on another replica
        world.clock.advance(REVOCATION_TTL + 1)
        assert attempt(dep, kind, victim, token) == (403, "principal_revoked")
    elif scenario == "revoked-with-fanout":
        token = dep.token(victim)
        assert attempt(dep, kind, victim, token) == (200, None)
        outcome = dep.revoke(admin, victim, hooks=True)
        assert outcome.fanout.complete
        assert attempt(dep, kind, victim, token) == (403, "principal_revoked")
    elif scenario == "policy-outage":
        dep.repo.fail_with(RuntimeError("policy store down"))
        assert attempt(dep, kind, victim, dep.token(victim)) == (503, "policy_store_unavailable")
        if kind == "api":
            _api_outage_all_routes(dep, victim)
    elif scenario == "policy-outage-after-cache-ttl":
        assert attempt(dep, kind, victim, dep.token(victim)) == (200, None)
        dep.repo.fail_with(RuntimeError("policy store down"))
        world.clock.advance(POLICY_CACHE_MAX_TTL)
        assert attempt(dep, kind, victim, dep.token(victim)) == (503, "policy_store_unavailable")
    elif scenario == "revocation-outage":
        dep.revocation_store.fail_with(RuntimeError("revocation store down"))
        assert attempt(dep, kind, victim, dep.token(victim)) == (
            503,
            "revocation_store_unavailable",
        )
    else:
        raise AssertionError(f"unknown lifecycle scenario {scenario}")
    probe_records = dep.audit_records()
    assert all(r.kind in ("after", "denied") for r in probe_records)


def _api_outage_all_routes(dep: Deployment, who: Who) -> None:
    headers = dep.bearer(who)
    target = who.domain_id
    for method, path, body in (
        ("GET", "/d/items", None),
        ("POST", "/d/query", {}),
        ("GET", f"/d/domains/{target}/items", None),
        ("GET", f"/d/resources/{C_FIN_1}", None),
        ("POST", "/d/export", {"domain_id": target}),
        ("GET", "/d/config", None),
        ("GET", "/audit/chains/contoso.finance/records", None),
    ):
        response = dep.client.request(method, path, headers=headers, json=body)
        assert response.status_code == 503, (path, response.text)
        assert "items" not in response.json()


# --------------------------------------------------------------------------- cache / push


def cache_read(
    dep: Deployment,
    cache: ScopeKeyedCache,
    scope: IdentityScope,
    ledger: Ledger,
    namespace: str = "catalog",
) -> list[str]:
    view = cache.get_view(scope, namespace)
    run(dep.audit.allow(scope, "data.read", target=None, domain=None))
    ledger.note(dep, "allow")
    return view


def expected_view(who: Who) -> set[str]:
    return set(domain_items(who.domain_id)) if who.role in READ_ROLES else set()


def run_cache_scenario(ro: World, scopes: dict[Who, IdentityScope], row: ScenarioCase) -> None:
    assert row.why.strip()
    name = row.scenario
    who = row.who
    if name == "pair":
        assert who is not None
        other = row.other
        assert other is not None
        a, b = who, other
        ledger = Ledger(ro)
        cache = ScopeKeyedCache(ro.clock)
        sa, sb = scopes[a], scopes[b]
        va = cache_read(ro[a.customer], cache, sa, ledger)
        vb = cache_read(ro[b.customer], cache, sb, ledger)
        assert scope_cache_key(sa, namespace="catalog") != scope_cache_key(sb, namespace="catalog")
        assert cache.loads == 2, "second principal was served the first principal's entry"
        assert set(va) == expected_view(a)
        assert set(vb) == expected_view(b)
        assert not set(vb) - expected_view(b), "leak into the second principal's view"
        ledger.verify()
        return
    if name == "policy_version":
        assert who is not None
        w1, w2 = build_world(), build_world(policy_version="2026.10.02-1")
        s1, s2 = w1[who.customer].scope(who), w2[who.customer].scope(who)
        assert s1.policy_version != s2.policy_version
        k1, k2 = scope_cache_key(s1, namespace="catalog"), scope_cache_key(s2, namespace="catalog")
        assert k1 != k2 and "pv=2026.10.01-1" in k1 and "pv=2026.10.02-1" in k2
        cache = ScopeKeyedCache(w1.clock)
        cache.get_view(s1)
        cache.get_view(s2)
        assert cache.loads == 2
        return
    if name == "grant_changes_key":
        assert who is not None
        plain, granted = build_world(), build_world(grants=privileged_grants())
        sp, sg = plain[who.customer].scope(who), granted[who.customer].scope(who)
        assert scope_cache_key(sp, namespace="catalog") != scope_cache_key(sg, namespace="catalog")
        cache = ScopeKeyedCache(plain.clock)
        assert set(cache.get_view(sp)) == set(domain_items(who.domain_id))
        assert set(cache.get_view(sg)) == set(domain_items(who.domain_id)) | {C_OPS_1}
        assert cache.loads == 2
        return
    if name == "grant_expiry":
        assert who is not None
        gw = build_world(grants=privileged_grants())
        dep = gw[who.customer]
        cache = ScopeKeyedCache(gw.clock)
        s1 = dep.scope(who)
        assert cache.get_view(s1) == [C_FIN_1]
        gw.clock.advance(GRANT_EXPIRES_IN + 1)
        s2 = dep.scope(who)
        assert scope_cache_key(s1, namespace="catalog") != scope_cache_key(s2, namespace="catalog")
        assert cache.get_view(s2) == [], "expired grant served from the grant-era entry"
        assert cache.loads == 2
        return
    if name == "namespace":
        assert who is not None
        scope = scopes[who]
        assert scope_cache_key(scope, namespace="catalog") != scope_cache_key(
            scope, namespace="search"
        )
        for bad in ("", "Bad NS", "a:b", "../x"):
            with pytest.raises(ValueError):
                scope_cache_key(scope, namespace=bad)
        return
    if name == "no_token_material":
        assert who is not None
        scope = scopes[who]
        key = scope_cache_key(scope, namespace="catalog")
        pid = principal_id_for(who)
        assert key.startswith(cache_key_prefix(scope))
        for secret in (who.object_id, pid, pid.rsplit(":", 1)[-1], TENANTS[who.customer]):
            assert secret not in key
        assert scope.scope_hash in key and scope.policy_version in key
        return
    if name == "non_server_scope":
        assert who is not None
        scope = scopes[who]
        for forged in (scope.to_contract(), {"customer_id": "contoso"}, "contoso", None):
            with pytest.raises(TypeError):
                scope_cache_key(forged, namespace="catalog")  # type: ignore[arg-type]
        return
    if name == "same_scope_as_rest":
        assert who is not None
        dep = ro[who.customer]
        scope = scopes[who]
        ledger = Ledger(ro)
        view = cache_read(dep, ScopeKeyedCache(ro.clock), scope, ledger)
        response = dep.client.get("/d/items", headers=dep.bearer(who))
        assert set(response.json()["items"]) == set(view) == expected_view(who)
        exported = dep.exporter.export(scope, domain_id=who.domain_id)
        assert set(exported) == set(view)
        # REST wrote one allow record of its own; the cache read wrote one more.
        ledger.note(dep, "allow")
        ledger.verify()
        return
    if name == "priv_view":
        assert who is not None
        gw = build_world(grants=privileged_grants())
        dep = gw[who.customer]
        ledger = Ledger(gw)
        view = cache_read(dep, ScopeKeyedCache(gw.clock), dep.scope(who), ledger)
        if who == ADMIN_C_FIN:
            assert set(view) == set(domain_items(who.domain_id)) | {C_OPS_1}
        else:
            assert set(view) == {C_OPS_1}
        ledger.verify()
        return
    if name == "priv_no_grant":
        assert who is not None
        ledger = Ledger(ro)
        view = cache_read(ro[who.customer], ScopeKeyedCache(ro.clock), scopes[who], ledger)
        assert set(view) == expected_view(who)
        assert all(i.split(":")[1] == who.customer for i in view)
        ledger.verify()
        return
    if name == "fanout_cache":
        assert who is not None and row.other is not None
        w = build_world()
        dep = w[who.customer]
        ledger = Ledger(w)
        victim_scope, bystander_scope = dep.scope(who), dep.scope(row.other)
        cache_read(dep, dep.cache, victim_scope, ledger)
        cache_read(dep, dep.cache, bystander_scope, ledger)
        before = len(dep.cache.entries)
        outcome = dep.revoke(ADMIN_C_FIN, who, hooks=True)
        assert outcome.fanout.invalidators_called == 3
        assert outcome.fanout.invalidators_failed == ()
        assert len(dep.cache.entries) == before - 1
        assert scope_cache_key(victim_scope, namespace="catalog") not in dep.cache.entries
        assert scope_cache_key(bystander_scope, namespace="catalog") in dep.cache.entries
        # the victim's policy cache entry was dropped by the deriver hook
        assert dep.deriver.invalidate_principal(principal_id_for(who)) == 0
        ledger.verify()
        return
    raise AssertionError(f"unknown cache scenario {name}")


def push_connect(dep: Deployment, scope: IdentityScope, domain: str, ledger: Ledger) -> None:
    try:
        dep.push.connect(scope, domain)
    except ForbiddenError as exc:
        run(
            dep.audit.deny(
                scope, "data.read", exc.reason or "forbidden", target=domain, domain=domain
            )
        )
        ledger.note(dep, "denied", exc.reason)
        raise
    run(dep.audit.allow(scope, "data.read", target=domain, domain=domain))
    ledger.note(dep, "allow")


def run_push_scenario(ro: World, scopes: dict[Who, IdentityScope], row: ScenarioCase) -> None:
    assert row.why.strip()
    name, _, arg = row.scenario.partition(":")
    if name == "connect":
        assert row.who is not None
        who = row.who
        dep = ro[who.customer]
        # fresh registry state per case; the shared world keeps only audit history
        dep.push.sessions.clear()
        ledger = Ledger(ro)
        if can_read(who, arg):
            push_connect(dep, scopes[who], arg, ledger)
            assert [s.domain_id for s in dep.push.sessions] == [arg]
        else:
            with pytest.raises(ForbiddenError) as raised:
                push_connect(dep, scopes[who], arg, ledger)
            assert raised.value.reason == "push_out_of_scope"
            assert dep.push.sessions == []
        ledger.verify()
        return
    if name == "delivery":
        w = build_world()
        ledger = Ledger(w)
        customer = arg.split(":")[1]
        dep = w[customer]
        for who in ALL_PRINCIPALS:
            if who.customer != customer:
                continue
            scope = dep.scope(who)
            try:
                push_connect(dep, scope, arg, ledger)
            except ForbiddenError:
                pass
        expected = {principal_id_for(x) for x in ALL_PRINCIPALS if can_read(x, arg)}
        assert set(dep.push.deliver(arg)) == expected
        assert all(w[c].push.deliver(arg) == [] for c in w.deployments if c != customer)
        ledger.verify()
        return
    if name == "protocol":
        w = build_world()
        assert isinstance(FakePushRegistry(w.clock), PushSessionRegistry)
        assert not isinstance(object(), PushSessionRegistry)
        return
    if name == "rejects_non_registry":
        hooks = RevocationHookRegistry()
        with pytest.raises(TypeError):
            hooks.register_push_registry("bogus", object())  # type: ignore[arg-type]
        assert hooks.push_registry_names == ()
        return
    if name == "fanout_closes":
        assert row.who is not None and row.other is not None
        w = build_world()
        dep = w[row.who.customer]
        ledger = Ledger(w)
        victim, bystander = dep.scope(row.who), dep.scope(row.other)
        push_connect(dep, victim, row.who.domain_id, ledger)
        push_connect(dep, victim, row.who.domain_id, ledger)
        push_connect(dep, bystander, row.other.domain_id, ledger)
        outcome = dep.revoke(ADMIN_C_FIN, row.who, hooks=True)
        assert outcome.fanout.complete and outcome.fanout.push_registries_called == 1
        assert outcome.fanout.sessions_closed == 2
        assert dep.push.closed_for == [principal_id_for(row.who)]
        assert dep.push.deliver(row.who.domain_id) == [principal_id_for(row.other)]
        ledger.verify()
        return
    if name == "fanout_failure_isolated":
        assert row.who is not None
        w = build_world()
        dep = w[row.who.customer]
        ledger = Ledger(w)
        push_connect(dep, dep.scope(row.who), row.who.domain_id, ledger)

        def broken_invalidator(principal_id: str) -> None:
            raise RuntimeError("cache backend down")

        dep.hooks.register_cache_invalidator("broken-cache", broken_invalidator)
        dep.hooks.register_push_registry("broken-push", FakePushRegistry(w.clock, fail=True))
        outcome = dep.revoke(ADMIN_C_FIN, row.who, hooks=True)
        assert not outcome.fanout.complete
        assert outcome.fanout.invalidators_failed == ("broken-cache",)
        assert outcome.fanout.push_registries_failed == ("broken-push",)
        assert outcome.fanout.sessions_closed == 1, "healthy registry must still close sessions"
        assert dep.push.deliver(row.who.domain_id) == []
        assert attempt(dep, "api", row.who, dep.token(row.who)) == (403, "principal_revoked")
        ledger.verify()
        return
    if name in ("priv_connect_granted_domain", "priv_auditor_connect", "priv_admin_own"):
        assert row.who is not None
        gw = build_world(grants=privileged_grants())
        dep = gw[row.who.customer]
        ledger = Ledger(gw)
        scope = dep.scope(row.who)
        if name == "priv_connect_granted_domain":
            with pytest.raises(ForbiddenError):
                push_connect(dep, scope, domain_id("contoso", "operations"), ledger)
        elif name == "priv_auditor_connect":
            assert row.who == AUDITOR_C_FIN
            for target in (row.who.domain_id, domain_id("contoso", "operations")):
                with pytest.raises(ForbiddenError):
                    push_connect(dep, scope, target, ledger)
        else:
            push_connect(dep, scope, row.who.domain_id, ledger)
            with pytest.raises(ForbiddenError):
                push_connect(dep, scope, domain_id("contoso", "operations"), ledger)
            assert [s.domain_id for s in dep.push.sessions] == [row.who.domain_id]
        ledger.verify()
        return
    raise AssertionError(f"unknown push scenario {name}")


# ------------------------------------------------------------------------ privileged only


def run_priv_api_scenario(row: ScenarioCase) -> None:
    gw = build_world(grants=privileged_grants())
    assert row.who is not None
    dep = gw[row.who.customer]
    if row.scenario == "api_expired_grant":
        who = AUDITOR_C_OPS
        path = f"/d/resources/{C_FIN_1}"
        assert dep.client.get(path, headers=dep.bearer(who)).status_code == 200
        gw.clock.advance(GRANT_EXPIRES_IN + 1)
        probe = AuditProbe(dep)
        response = dep.client.get(path, headers=dep.bearer(who))
        assert response.status_code == 403
        assert response.json()["reason"] == "target_out_of_scope"
        probe.assert_decision("denied", who=who, reason="target_out_of_scope")
    elif row.scenario == "role_expiry":
        who = ADMIN_C_FIN
        assert dep.client.get("/d/config", headers=dep.bearer(who)).status_code == 200
        assert (
            dep.client.get(f"/d/domains/{who.domain_id}/items", headers=dep.bearer(who)).status_code
            == 200
        )
        gw.clock.advance(7 * 24 * 3600 + 1)
        probe = AuditProbe(dep)
        response = dep.client.get("/d/config", headers=dep.bearer(who))
        assert response.status_code == 403
        assert response.json()["reason"] == "permission_missing"
        read = dep.client.get(f"/d/domains/{who.domain_id}/items", headers=dep.bearer(who))
        assert read.status_code == 403
        assert len(probe.new()) == 2
    else:
        raise AssertionError(f"unknown privileged scenario {row.scenario}")
