"""The reason-tracked case table for the ABAC negative suite (PRP-06 item 6).

Every row carries ``why`` (a mandatory, human-written reason the case exists) plus the expected
outcome and the expected audit decision. Expected results come from the independent oracle below
(a static restatement of the NS-08 role table), never from the code under test.

``case_manifest.json`` is the committed ledger of case ids. ``test_coverage.py`` fails when a case
disappears from the table without a ``removed`` entry that carries a reason, when a case appears
without being added to the ledger, or when a path kind has no cases.

Audit expectations: ``allow`` / ``denied`` (exactly one new record with that decision) or
``none``, which requires ``gap`` to say why the implementation cannot audit it (reported to the
orchestrator, never silently accepted).
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field, replace
from typing import Any, Final, Literal

from neurosphere_core.auth.scope import PolicyGrant, Role

from .world import (
    ALL_DOMAIN_IDS,
    ALL_PRINCIPALS,
    CUSTOMERS,
    DOMAINS,
    Who,
    domain_id,
    item_id,
    make_grant,
)

Kind = Literal["api", "search", "export", "cache", "push"]
KINDS: Final[tuple[Kind, ...]] = ("api", "search", "export", "cache", "push")
Audit = Literal["allow", "denied", "none"]

GAP_NO_SCOPE: Final = (
    "no scope exists (401/503 or revoked before derivation): the implementation has no audit "
    "seam for requests that fail before an IdentityScope is derived"
)
GAP_AUDIT_ROUTE_ALLOW: Final = (
    "item 4 audit router has no allow hook; require() only exposes a denial recorder"
)

READ_ROLES: Final = frozenset({Role.VIEWER, Role.ANALYST, Role.DOMAIN_STEWARD, Role.ADMIN})
EXPORT_ROLES: Final = frozenset({Role.ANALYST, Role.DOMAIN_STEWARD})


def short(target_domain_id: str) -> str:
    return f"{target_domain_id.split(':')[1]}.{target_domain_id.rsplit(':', 1)[-1]}"


def domain_items(target_domain_id: str) -> frozenset[str]:
    customer = target_domain_id.split(":")[1]
    name = target_domain_id.rsplit(":", 1)[-1]
    return frozenset(item_id(customer, name, n) for n in (1, 2))


def domain_docs(target_domain_id: str) -> frozenset[str]:
    return domain_items(target_domain_id) | {target_domain_id}


def can_read(who: Who, target_domain_id: str) -> bool:
    return who.role in READ_ROLES and target_domain_id == who.domain_id


def can_export(who: Who, target_domain_id: str) -> bool:
    return who.role in EXPORT_ROLES and target_domain_id == who.domain_id


def p(customer: str, domain: str, role: Role) -> Who:
    return Who(customer, domain, role)


# Policy grants used by the privileged-role world. Keys are principals; all grants are reads on
# exactly one resource, time-bound, with a reason (C7).
C_OPS_1 = item_id("contoso", "operations", 1)
C_OPS_2 = item_id("contoso", "operations", 2)
C_FIN_1 = item_id("contoso", "finance", 1)
C_FIN_2 = item_id("contoso", "finance", 2)
F_FIN_1 = item_id("fabrikam", "finance", 1)

ADMIN_C_FIN = p("contoso", "finance", Role.ADMIN)
AUDITOR_C_FIN = p("contoso", "finance", Role.SECURITY_AUDITOR)
AUDITOR_C_OPS = p("contoso", "operations", Role.SECURITY_AUDITOR)
ANALYST_C_FIN = p("contoso", "finance", Role.ANALYST)
ADMIN_C_OPS = p("contoso", "operations", Role.ADMIN)

GRANT_EXPIRES_IN: Final = 600.0


def privileged_grants() -> Mapping[Who, tuple[PolicyGrant, ...]]:
    return {
        ADMIN_C_FIN: (
            make_grant(C_OPS_1, "read", grant_id="g-admin-ops1"),
            make_grant(F_FIN_1, "read", grant_id="g-admin-foreign"),
        ),
        AUDITOR_C_FIN: (make_grant(C_OPS_1, "read", grant_id="g-aud-ops1"),),
        AUDITOR_C_OPS: (
            make_grant(C_FIN_1, "read", grant_id="g-aud-fin1", expires_in=GRANT_EXPIRES_IN),
        ),
        ANALYST_C_FIN: (make_grant(C_OPS_1, "export", grant_id="g-analyst-ops1-export"),),
    }


@dataclass(frozen=True, kw_only=True, eq=False)
class CaseBase:
    id: str
    kind: Kind
    why: str
    audit: Audit
    gap: str = ""


@dataclass(frozen=True, kw_only=True, eq=False)
class ApiCase(CaseBase):
    kind: Kind = "api"
    who: Who
    app: str
    method: str = "GET"
    path: str
    auth: str = "own"
    headers: Mapping[str, str] = field(default_factory=dict)
    params: Mapping[str, str] = field(default_factory=dict)
    body: Any = None
    claims: Mapping[str, Any] = field(default_factory=dict)
    status: int
    reason: str | None
    items: frozenset[str] | None = None
    world: Literal["ro", "grant"] = "ro"


@dataclass(frozen=True, kw_only=True, eq=False)
class SearchCase(CaseBase):
    kind: Kind = "search"
    who: Who
    raw_filters: Mapping[str, Any] = field(default_factory=dict)
    expected_ids: frozenset[str] = frozenset()
    decision: str
    refused: bool = False
    world: Literal["ro", "grant"] = "ro"
    advance: float = 0.0


@dataclass(frozen=True, kw_only=True, eq=False)
class ExportCase(CaseBase):
    kind: Kind = "export"
    who: Who
    target_domain: str | None = None
    target_resource: str | None = None
    status: int
    http_reason: str | None
    direct_reason: str | None
    items: frozenset[str] = frozenset()
    world: Literal["ro", "grant"] = "ro"


@dataclass(frozen=True, kw_only=True, eq=False)
class ScenarioCase(CaseBase):
    """Cache, push, privileged and lifecycle rows executed by a named scenario."""

    who: Who | None = None
    other: Who | None = None
    scenario: str


def _short_who(who: Who) -> str:
    return who.label


# ----------------------------------------------------------------------------------- API


def _api_domain_matrix() -> Iterator[ApiCase]:
    for who in ALL_PRINCIPALS:
        for target in ALL_DOMAIN_IDS:
            ok = can_read(who, target)
            if ok:
                why = "positive control: a read-capable role reads its own domain"
            elif target == who.domain_id:
                why = "own domain without data.read (auditor reads evidence, not data)"
            elif target.split(":")[1] == who.customer:
                why = "cross-domain read inside one customer"
            else:
                why = "cross-customer read: foreign customer domain id on the caller deployment"
            yield ApiCase(
                id=f"api.domain-read.{who.label}->{short(target)}",
                why=why,
                audit="allow" if ok else "denied",
                who=who,
                app=who.customer,
                path=f"/d/domains/{target}/items",
                status=200 if ok else 403,
                reason=None if ok else "target_out_of_scope",
                items=domain_items(target) if ok else None,
            )


def _api_resource_matrix() -> Iterator[ApiCase]:
    for who in ALL_PRINCIPALS:
        for target in ALL_DOMAIN_IDS:
            resource = domain_items_first(target)
            yield ApiCase(
                id=f"api.resource-read.{who.label}->{short(target)}.1",
                why="by-resource route needs an explicit scoped grant; a domain role alone "
                "(even over the owning domain) does not authorize it",
                audit="denied",
                who=who,
                app=who.customer,
                path=f"/d/resources/{resource}",
                status=403,
                reason="target_out_of_scope",
            )


def domain_items_first(target_domain_id: str) -> str:
    return sorted(domain_items(target_domain_id))[0]


def _api_token_replay() -> Iterator[ApiCase]:
    for who in ALL_PRINCIPALS:
        other = next(c for c in CUSTOMERS if c != who.customer)
        yield ApiCase(
            id=f"api.token-replay.{who.label}->{other}",
            why="a valid token of customer A presented to customer B deployment (issuer/key/"
            "tenant mismatch) must be rejected at authentication",
            audit="none",
            gap=GAP_NO_SCOPE,
            who=who,
            app=other,
            path="/d/items",
            status=401,
            reason="unknown_kid",
        )


_UNAUTH: Final = (
    ("none", "missing_token", "no Authorization header"),
    ("garbage", "malformed_token", "unparseable bearer value"),
    ("scheme", "invalid_scheme", "non-bearer scheme"),
    ("expired", "expired", "expired token"),
    ("wrong_audience", "wrong_audience", "token minted for a different audience"),
    ("wrong_key", "unknown_kid", "token signed by a key the deployment does not trust"),
)


def _api_unauth() -> Iterator[ApiCase]:
    who = p("contoso", "finance", Role.VIEWER)
    for mode, reason, what in _UNAUTH:
        yield ApiCase(
            id=f"api.unauth.{mode}",
            why=f"authentication must fail closed: {what}",
            audit="none",
            gap=GAP_NO_SCOPE,
            who=who,
            app="contoso",
            path="/d/items",
            auth=mode,
            status=401,
            reason=reason,
        )


def _api_forged() -> Iterator[ApiCase]:
    targets = (("contoso", "finance"), ("fabrikam", "operations"))
    for customer, domain in targets:
        other_domain = next(d for d in DOMAINS if d != domain)
        foreign_customer = next(c for c in CUSTOMERS if c != customer)
        forged_domain = domain_id(customer, other_domain)
        foreign_domain = domain_id(foreign_customer, domain)
        vectors: tuple[tuple[str, str, str, dict[str, Any]], ...] = (
            ("header-domain", "GET", "/d/items", {"headers": {"X-Domain-Id": forged_domain}}),
            (
                "header-customer",
                "GET",
                "/d/items",
                {"headers": {"X-Customer-Id": foreign_customer, "X-Domain-Id": foreign_domain}},
            ),
            ("query-domain", "GET", "/d/items", {"params": {"domain_id": forged_domain}}),
            (
                "body-domain",
                "POST",
                "/d/query",
                {
                    "body": {
                        "domain_id": forged_domain,
                        "customer_id": foreign_customer,
                        "allowed_domains": list(ALL_DOMAIN_IDS),
                    }
                },
            ),
            (
                "token-claim",
                "GET",
                "/d/items",
                {
                    "claims": {
                        "domain_id": forged_domain,
                        "customer_id": foreign_customer,
                        "allowed_domains": list(ALL_DOMAIN_IDS),
                    }
                },
            ),
        )
        for role in (
            Role.VIEWER,
            Role.ANALYST,
            Role.DOMAIN_STEWARD,
            Role.ADMIN,
            Role.SECURITY_AUDITOR,
        ):
            who = p(customer, domain, role)
            readable = role in READ_ROLES
            for vector, method, path, extra in vectors:
                yield ApiCase(
                    id=f"api.forged.{vector}.{who.label}",
                    why="caller-supplied domain/customer in "
                    f"{vector.replace('-', ' ')} must never influence scope: result is limited "
                    "to the server-derived scope"
                    + ("" if readable else " (auditor has no data.read anywhere)"),
                    audit="allow" if readable else "denied",
                    who=who,
                    app=customer,
                    method=method,
                    path=path,
                    status=200 if readable else 403,
                    reason=None if readable else "permission_missing",
                    items=domain_items(who.domain_id) if readable else None,
                    **extra,
                )


def _api_config() -> Iterator[ApiCase]:
    for who in ALL_PRINCIPALS:
        ok = who.role is Role.ADMIN
        yield ApiCase(
            id=f"api.config.{who.label}",
            why="config.manage is Admin-only"
            if not ok
            else "positive control: Admin manages configuration within its domains",
            audit="allow" if ok else "denied",
            who=who,
            app=who.customer,
            path="/d/config",
            status=200 if ok else 403,
            reason=None if ok else "permission_missing",
        )


# --------------------------------------------------------------------------------- search


def _visible(who: Who) -> frozenset[str]:
    return frozenset({who.domain_id}) if who.role in READ_ROLES else frozenset()


def _search_decision(who: Who, requested: tuple[str, ...] | None) -> str:
    visible = _visible(who)
    if not visible:
        return "permission_missing"
    if requested and not set(requested) <= visible:
        return "filter_out_of_scope"
    return "allow"


def _search_matrix() -> Iterator[SearchCase]:
    for who in ALL_PRINCIPALS:
        variants: list[tuple[str, tuple[str, ...] | None]] = [("nofilter", None)]
        variants += [(f"narrow-{short(t)}", (t,)) for t in ALL_DOMAIN_IDS]
        variants.append(("widen-all", ALL_DOMAIN_IDS))
        for name, requested in variants:
            visible = _visible(who)
            pool = visible if requested is None else visible & set(requested)
            expected = frozenset().union(*(domain_docs(d) for d in pool)) if pool else frozenset()
            decision = _search_decision(who, requested)
            leak = (
                "no filter: server-side scope alone bounds the results"
                if requested is None
                else "caller domain filter can only narrow; asking for domains outside the "
                "scope must not widen it"
            )
            yield SearchCase(
                id=f"search.{who.label}.{name}",
                why=leak,
                audit="allow" if decision == "allow" else "denied",
                who=who,
                raw_filters={} if requested is None else {"domain_ids": list(requested)},
                expected_ids=expected,
                decision=decision,
            )


_REFUSED: Final = (
    ("customer-id", {"customer_id": "fabrikam"}),
    ("allowed-domains", {"allowed_domains": list(ALL_DOMAIN_IDS)}),
    ("scope", {"scope": {"allowed_domains": list(ALL_DOMAIN_IDS)}}),
    (
        "or-clause",
        {"domain_ids": [ALL_DOMAIN_IDS[0]], "or": [{"domain_ids": list(ALL_DOMAIN_IDS)}]},
    ),
    ("odata", {"$filter": "domain_id ne ''"}),
    ("wildcard-domain", {"domain_ids": ["*"]}),
)


def _search_refused() -> Iterator[SearchCase]:
    for who in (p("contoso", "finance", Role.VIEWER), p("fabrikam", "operations", Role.ADMIN)):
        for name, raw in _REFUSED:
            yield SearchCase(
                id=f"search.refused.{name}.{who.label}",
                why="the structured filter schema is closed: a field or value that could widen "
                "scope is refused before any search runs",
                audit="denied",
                who=who,
                raw_filters=raw,
                decision="filter_widening_refused",
                refused=True,
            )


def _search_privileged() -> Iterator[SearchCase]:
    own_admin = domain_docs(ADMIN_C_FIN.domain_id)
    granted = frozenset({C_OPS_1})
    rows = [
        (
            "admin-no-grant-other-domain",
            ADMIN_C_OPS,
            {},
            domain_docs(ADMIN_C_OPS.domain_id),
            "allow",
            "ro",
            0.0,
            "positive control: an Admin without a grant sees only its own domain",
        ),
        (
            "admin-granted-nofilter",
            ADMIN_C_FIN,
            {},
            own_admin | granted,
            "allow",
            "grant",
            0.0,
            "a scoped read grant adds exactly the granted resource, not its domain",
        ),
        (
            "admin-granted-filter-ops",
            ADMIN_C_FIN,
            {"domain_ids": [domain_id("contoso", "operations")]},
            granted,
            "allow",
            "grant",
            0.0,
            "filtering to the granted resource's domain still yields only the granted resource",
        ),
        (
            "admin-granted-filter-fabrikam",
            ADMIN_C_FIN,
            {"domain_ids": [domain_id("fabrikam", "finance")]},
            frozenset(),
            "filter_out_of_scope",
            "grant",
            0.0,
            "a grant naming another customer's resource is dropped at derivation; the foreign "
            "domain stays unreachable",
        ),
    ]
    for rid, who, raw, expected, decision, world, advance, why in rows:
        yield SearchCase(
            id=f"search.priv.{rid}",
            why=why,
            audit="allow" if decision == "allow" else "denied",
            who=who,
            raw_filters=raw,
            expected_ids=expected,
            decision=decision,
            world=world,  # type: ignore[arg-type]
            advance=advance,
        )
    yield SearchCase(
        id="search.priv.auditor-no-grant",
        why="Auditor reads audit and evidence, not data: with no grant search returns nothing",
        audit="denied",
        who=AUDITOR_C_FIN,
        expected_ids=frozenset(),
        decision="permission_missing",
        world="ro",
    )
    yield SearchCase(
        id="search.priv.auditor-granted",
        why="an Auditor with a scoped read grant sees only the granted resource",
        audit="allow",
        who=AUDITOR_C_FIN,
        expected_ids=frozenset({C_OPS_1}),
        decision="allow",
        world="grant",
    )
    yield SearchCase(
        id="search.priv.auditor-granted-own-domain-filter",
        why="a grant never opens the Auditor's own domain; filtering to it yields nothing "
        "beyond the granted resource",
        audit="denied",
        who=AUDITOR_C_FIN,
        raw_filters={"domain_ids": [AUDITOR_C_FIN.domain_id]},
        expected_ids=frozenset(),
        decision="filter_out_of_scope",
        world="grant",
    )
    yield SearchCase(
        id="search.priv.auditor-expired-grant",
        why="after the grant expires (fake clock) the Auditor sees nothing again",
        audit="denied",
        who=AUDITOR_C_OPS,
        expected_ids=frozenset(),
        decision="permission_missing",
        world="grant",
        advance=GRANT_EXPIRES_IN + 1,
    )
    yield SearchCase(
        id="search.priv.auditor-unexpired-grant",
        why="positive control for the expiry case: before expiry the granted resource is visible",
        audit="allow",
        who=AUDITOR_C_OPS,
        expected_ids=frozenset({C_FIN_1}),
        decision="allow",
        world="grant",
    )


# ---------------------------------------------------------------------------------- export


def _export_matrix() -> Iterator[ExportCase]:
    for who in ALL_PRINCIPALS:
        for target in ALL_DOMAIN_IDS:
            ok = can_export(who, target)
            lacks_perm = who.role not in EXPORT_ROLES
            if ok:
                why = "positive control: Analyst/Steward exports its own domain"
            elif lacks_perm:
                why = "role lacks data.export (Viewer, Admin, Auditor) on any domain"
            elif target.split(":")[1] == who.customer:
                why = "cross-domain export inside one customer"
            else:
                why = "cross-customer export with a forged foreign domain id in the body"
            yield ExportCase(
                id=f"export.domain.{who.label}->{short(target)}",
                why=why,
                audit="allow" if ok else "denied",
                who=who,
                target_domain=target,
                status=200 if ok else 403,
                http_reason=None
                if ok
                else ("permission_missing" if lacks_perm else "export_out_of_scope"),
                direct_reason=None if ok else "export_out_of_scope",
                items=domain_items(target) if ok else frozenset(),
            )


def _export_resource_and_empty() -> Iterator[ExportCase]:
    for who in ALL_PRINCIPALS:
        if who.role not in EXPORT_ROLES:
            continue
        yield ExportCase(
            id=f"export.resource.{who.label}",
            why="export by resource id needs an explicit export grant; owning the domain is "
            "not enough",
            audit="denied",
            who=who,
            target_resource=domain_items_first(who.domain_id),
            status=403,
            http_reason="export_out_of_scope",
            direct_reason="export_out_of_scope",
        )
        yield ExportCase(
            id=f"export.no-target.{who.label}",
            why="an export with no explicit target must not default to everything visible",
            audit="denied",
            who=who,
            status=403,
            http_reason="export_target_required",
            direct_reason="export_target_required",
        )


def _export_privileged() -> Iterator[ExportCase]:
    yield ExportCase(
        id="export.priv.analyst-export-grant-resource",
        why="positive control: an export grant on one resource exports exactly that resource",
        audit="allow",
        who=ANALYST_C_FIN,
        target_resource=C_OPS_1,
        status=200,
        http_reason=None,
        direct_reason=None,
        items=frozenset({C_OPS_1}),
        world="grant",
    )
    yield ExportCase(
        id="export.priv.analyst-export-grant-neighbour",
        why="the export grant does not extend to the neighbouring resource",
        audit="denied",
        who=ANALYST_C_FIN,
        target_resource=C_OPS_2,
        status=403,
        http_reason="export_out_of_scope",
        direct_reason="export_out_of_scope",
        world="grant",
    )
    yield ExportCase(
        id="export.priv.analyst-export-grant-domain",
        why="the export grant does not open the granted resource's whole domain",
        audit="denied",
        who=ANALYST_C_FIN,
        target_domain=domain_id("contoso", "operations"),
        status=403,
        http_reason="export_out_of_scope",
        direct_reason="export_out_of_scope",
        world="grant",
    )
    yield ExportCase(
        id="export.priv.admin-read-grant-is-not-export",
        why="a read grant on a resource confers no export right",
        audit="denied",
        who=ADMIN_C_FIN,
        target_resource=C_OPS_1,
        status=403,
        http_reason="permission_missing",
        direct_reason="export_out_of_scope",
        world="grant",
    )
    yield ExportCase(
        id="export.priv.auditor-read-grant-is-not-export",
        why="an Auditor with a read grant still cannot export it",
        audit="denied",
        who=AUDITOR_C_FIN,
        target_resource=C_OPS_1,
        status=403,
        http_reason="permission_missing",
        direct_reason="export_out_of_scope",
        world="grant",
    )


# ----------------------------------------------------------------------- scenario tables


def _cache_pairs() -> Iterator[ScenarioCase]:
    n = len(ALL_PRINCIPALS)
    for i in range(n):
        for j in range(i + 1, n):
            a, b = ALL_PRINCIPALS[i], ALL_PRINCIPALS[j]
            if a.customer != b.customer:
                why = "cross-customer pair: keys and views must never be shared"
            elif a.domain != b.domain:
                why = "cross-domain pair inside one customer: keys and views must differ"
            else:
                why = "same domain, different role/user: scope hash differs so keys differ"
            yield ScenarioCase(
                id=f"cache.pair.{a.label}|{b.label}",
                kind="cache",
                why=why,
                audit="allow",
                scenario="pair",
                who=a,
                other=b,
            )


def _cache_special() -> Iterator[ScenarioCase]:
    yield ScenarioCase(
        id="cache.policy-version-bump",
        kind="cache",
        why="a policy version bump must move the same principal to new cache keys",
        audit="allow",
        scenario="policy_version",
        who=p("contoso", "finance", Role.ANALYST),
    )
    yield ScenarioCase(
        id="cache.grant-changes-key",
        kind="cache",
        why="adding a scoped grant changes the scope hash and therefore the key and the view",
        audit="allow",
        scenario="grant_changes_key",
        who=ADMIN_C_FIN,
    )
    yield ScenarioCase(
        id="cache.grant-expiry-changes-key",
        kind="cache",
        why="after a grant expires the principal must not be served the grant-era entry",
        audit="allow",
        scenario="grant_expiry",
        who=AUDITOR_C_OPS,
    )
    yield ScenarioCase(
        id="cache.namespace-isolation",
        kind="cache",
        why="one principal in two cache namespaces must not share keys",
        audit="allow",
        scenario="namespace",
        who=p("contoso", "finance", Role.VIEWER),
    )
    yield ScenarioCase(
        id="cache.key-has-no-token-material",
        kind="cache",
        why="cache keys carry the scope hash only: no object id, token or principal id",
        audit="allow",
        scenario="no_token_material",
        who=p("fabrikam", "operations", Role.DOMAIN_STEWARD),
    )
    yield ScenarioCase(
        id="cache.rejects-non-server-scope",
        kind="cache",
        why="only a server-derived IdentityScope may key a cache entry (no dict, no contract)",
        audit="allow",
        scenario="non_server_scope",
        who=p("contoso", "finance", Role.VIEWER),
    )
    yield ScenarioCase(
        id="cache.same-scope-object-as-rest",
        kind="cache",
        why="the cache view equals the REST view because both use the same scope object",
        audit="allow",
        scenario="same_scope_as_rest",
        who=p("contoso", "finance", Role.ANALYST),
    )


def _cache_priv() -> Iterator[ScenarioCase]:
    for who, why in (
        (ADMIN_C_FIN, "Admin view with a grant is exactly its domain plus the granted resource"),
        (AUDITOR_C_FIN, "Auditor view with a grant is exactly the granted resource"),
    ):
        yield ScenarioCase(
            id=f"cache.priv.view.{who.label}",
            kind="cache",
            why=why,
            audit="allow",
            scenario="priv_view",
            who=who,
        )
    for who in (
        p("contoso", "finance", Role.ADMIN),
        p("fabrikam", "operations", Role.SECURITY_AUDITOR),
    ):
        yield ScenarioCase(
            id=f"cache.priv.no-grant-view.{who.label}",
            kind="cache",
            why="privileged role without a grant never gets another domain or customer in its "
            "cached view",
            audit="allow",
            scenario="priv_no_grant",
            who=who,
        )


def _push_matrix() -> Iterator[ScenarioCase]:
    for who in ALL_PRINCIPALS:
        for target in ALL_DOMAIN_IDS:
            ok = can_read(who, target)
            if ok:
                why = "positive control: subscribe to the caller's own domain"
            elif target == who.domain_id:
                why = "own domain without data.read: auditor may not subscribe to data events"
            elif target.split(":")[1] == who.customer:
                why = "cross-domain push subscription inside one customer"
            else:
                why = "cross-customer push subscription with a forged foreign domain id"
            yield ScenarioCase(
                id=f"push.connect.{who.label}->{short(target)}",
                kind="push",
                why=why,
                audit="allow" if ok else "denied",
                scenario=f"connect:{target}",
                who=who,
            )


def _push_special() -> Iterator[ScenarioCase]:
    for target in ALL_DOMAIN_IDS:
        yield ScenarioCase(
            id=f"push.delivery.{short(target)}",
            kind="push",
            why="an event in a domain reaches exactly the sessions authorized for that domain",
            audit="allow",
            scenario=f"delivery:{target}",
        )
    yield ScenarioCase(
        id="push.interface.protocol",
        kind="push",
        why="C13: only the PushSessionRegistry interface exists; the gateway is PRP-18",
        audit="allow",
        scenario="protocol",
    )
    yield ScenarioCase(
        id="push.interface.rejects-non-registry",
        kind="push",
        why="an object without close_for_principal must not be registerable as a push closer",
        audit="allow",
        scenario="rejects_non_registry",
    )
    yield ScenarioCase(
        id="push.fanout.closes-only-target",
        kind="push",
        why="revocation closes every session of the revoked principal and nobody else's",
        audit="allow",
        scenario="fanout_closes",
        who=p("contoso", "finance", Role.ANALYST),
        other=p("contoso", "finance", Role.VIEWER),
    )
    yield ScenarioCase(
        id="push.fanout.failing-hook-does-not-abort",
        kind="push",
        why="a failing push registry or cache invalidator must not stop the remaining hooks",
        audit="allow",
        scenario="fanout_failure_isolated",
        who=p("contoso", "finance", Role.ANALYST),
    )
    yield ScenarioCase(
        id="push.priv.admin-granted-resource-is-not-a-domain",
        kind="push",
        why="a resource grant does not allow a domain-level push subscription",
        audit="denied",
        scenario="priv_connect_granted_domain",
        who=ADMIN_C_FIN,
    )
    yield ScenarioCase(
        id="push.priv.auditor-cannot-subscribe",
        kind="push",
        why="Auditor has no data.read, so no data push subscription even with a grant",
        audit="denied",
        scenario="priv_auditor_connect",
        who=AUDITOR_C_FIN,
    )
    yield ScenarioCase(
        id="push.priv.admin-own-domain",
        kind="push",
        why="positive control: Admin subscribes to its own domain only",
        audit="allow",
        scenario="priv_admin_own",
        who=ADMIN_C_FIN,
    )


def _cache_fanout() -> Iterator[ScenarioCase]:
    yield ScenarioCase(
        id="cache.fanout.invalidates-target-only",
        kind="cache",
        why="revocation fans out to every cache invalidator: the target's entries and policy "
        "cache are dropped, a bystander's are kept",
        audit="allow",
        scenario="fanout_cache",
        who=p("contoso", "finance", Role.ANALYST),
        other=p("contoso", "finance", Role.VIEWER),
    )


_LIFECYCLE_SCENARIOS: Final = (
    (
        "revoked-after-ttl",
        "revoked principal (revocation on another replica) is denied on this "
        "path after the TTL, using a token issued before the revocation",
    ),
    (
        "revoked-with-fanout",
        "revocation on this replica denies at once (fan-out invalidated the caches)",
    ),
    ("policy-outage", "policy store outage must yield 503 and never an allow"),
    (
        "policy-outage-after-cache-ttl",
        "a cached policy is not served past its TTL during an outage",
    ),
    ("revocation-outage", "revocation store outage must yield 503 and never an allow"),
)


def _lifecycle() -> Iterator[ScenarioCase]:
    for kind in KINDS:
        for scenario, why in _LIFECYCLE_SCENARIOS:
            yield ScenarioCase(
                id=f"{kind}.lifecycle.{scenario}",
                kind=kind,
                why=why,
                audit="none",
                gap=GAP_NO_SCOPE,
                scenario=scenario,
                who=p("contoso", "finance", Role.ANALYST),
            )


def _api_privileged() -> Iterator[ApiCase]:
    cdom = domain_id("contoso", "operations")
    yield ApiCase(
        id="api.priv.admin-granted-resource",
        why="Admin with a scoped read grant reads exactly the granted resource",
        audit="allow",
        who=ADMIN_C_FIN,
        app="contoso",
        path=f"/d/resources/{C_OPS_1}",
        status=200,
        reason=None,
        items=frozenset({C_OPS_1}),
    )
    yield ApiCase(
        id="api.priv.admin-granted-neighbour",
        why="the grant does not cover the neighbouring resource in the same domain",
        audit="denied",
        who=ADMIN_C_FIN,
        app="contoso",
        path=f"/d/resources/{C_OPS_2}",
        status=403,
        reason="target_out_of_scope",
    )
    yield ApiCase(
        id="api.priv.admin-granted-domain-route",
        why="a resource grant does not open the owning domain",
        audit="denied",
        who=ADMIN_C_FIN,
        app="contoso",
        path=f"/d/domains/{cdom}/items",
        status=403,
        reason="target_out_of_scope",
    )
    yield ApiCase(
        id="api.priv.admin-granted-listing",
        why="the scoped listing contains the Admin's own domain plus only the granted resource",
        audit="allow",
        who=ADMIN_C_FIN,
        app="contoso",
        path="/d/items",
        status=200,
        reason=None,
        items=domain_items(ADMIN_C_FIN.domain_id) | {C_OPS_1},
    )
    yield ApiCase(
        id="api.priv.admin-foreign-customer-grant",
        why="a policy grant naming another customer's resource is dropped at derivation",
        audit="denied",
        who=ADMIN_C_FIN,
        app="contoso",
        path=f"/d/resources/{F_FIN_1}",
        status=403,
        reason="target_out_of_scope",
    )
    yield ApiCase(
        id="api.priv.admin-no-grant-other-domain",
        why="Admin without a grant cannot read another domain (no bypass, C7)",
        audit="denied",
        who=ADMIN_C_OPS,
        app="contoso",
        path=f"/d/domains/{domain_id('contoso', 'finance')}/items",
        status=403,
        reason="target_out_of_scope",
    )
    yield ApiCase(
        id="api.priv.auditor-granted-resource",
        why="Auditor with a scoped read grant reads exactly the granted resource",
        audit="allow",
        who=AUDITOR_C_FIN,
        app="contoso",
        path=f"/d/resources/{C_OPS_1}",
        status=200,
        reason=None,
        items=frozenset({C_OPS_1}),
    )
    yield ApiCase(
        id="api.priv.auditor-granted-neighbour",
        why="Auditor's grant does not cover the neighbouring resource",
        audit="denied",
        who=AUDITOR_C_FIN,
        app="contoso",
        path=f"/d/resources/{C_OPS_2}",
        status=403,
        reason="target_out_of_scope",
    )
    yield ApiCase(
        id="api.priv.auditor-granted-listing",
        why="Auditor listing is exactly the granted resource and nothing from its own domain",
        audit="allow",
        who=AUDITOR_C_FIN,
        app="contoso",
        path="/d/items",
        status=200,
        reason=None,
        items=frozenset({C_OPS_1}),
    )
    yield ApiCase(
        id="api.priv.auditor-own-domain-data",
        why="Auditor reads audit and evidence, not data, even in its own domain",
        audit="denied",
        who=AUDITOR_C_FIN,
        app="contoso",
        path=f"/d/domains/{AUDITOR_C_FIN.domain_id}/items",
        status=403,
        reason="target_out_of_scope",
    )
    yield ApiCase(
        id="api.priv.auditor-unexpired-grant",
        why="positive control for expiry: the grant works before it expires",
        audit="allow",
        who=AUDITOR_C_OPS,
        app="contoso",
        path=f"/d/resources/{C_FIN_1}",
        status=200,
        reason=None,
        items=frozenset({C_FIN_1}),
    )
    yield ApiCase(
        id="api.priv.auditor-audit-own-chain",
        why="positive control: Auditor reads the audit chain of its own domain",
        audit="none",
        gap=GAP_AUDIT_ROUTE_ALLOW,
        who=AUDITOR_C_FIN,
        app="contoso",
        path="/audit/chains/contoso.finance/records",
        status=200,
        reason=None,
    )
    yield ApiCase(
        id="api.priv.auditor-audit-other-domain-chain",
        why="Auditor cannot read the audit chain of another domain without a grant",
        audit="denied",
        who=AUDITOR_C_FIN,
        app="contoso",
        path="/audit/chains/contoso.operations/records",
        status=403,
        reason="target_out_of_scope",
    )
    yield ApiCase(
        id="api.priv.auditor-audit-platform-chain",
        why="the customer-wide platform chain is not a domain the Auditor holds",
        audit="denied",
        who=AUDITOR_C_FIN,
        app="contoso",
        path="/audit/chains/contoso.platform/records",
        status=403,
        reason="target_out_of_scope",
    )
    yield ApiCase(
        id="api.priv.auditor-audit-audit-chain-out-of-scope-customer",
        why="a foreign customer's chain id is refused (and the refusal must be audited)",
        audit="denied",
        who=AUDITOR_C_FIN,
        app="contoso",
        path="/audit/chains/fabrikam.finance/records",
        status=403,
        reason="audit_chain_out_of_scope",
    )
    yield ApiCase(
        id="api.priv.auditor-audit-customer-wide-chain",
        why="a customer-wide chain id (no domain part) is refused (and must be audited)",
        audit="denied",
        who=AUDITOR_C_FIN,
        app="contoso",
        path="/audit/chains/contoso/records",
        status=403,
        reason="audit_chain_out_of_scope",
    )
    yield ApiCase(
        id="api.priv.auditor-verify-other-domain-chain",
        why="chain verification is reading: same domain confinement as records",
        audit="denied",
        who=AUDITOR_C_FIN,
        app="contoso",
        path="/audit/chains/contoso.operations/verify",
        status=403,
        reason="target_out_of_scope",
    )
    for role in (Role.VIEWER, Role.ANALYST, Role.DOMAIN_STEWARD, Role.ADMIN):
        who = p("contoso", "finance", role)
        yield ApiCase(
            id=f"api.priv.audit-read.{who.label}",
            why="audit.read belongs to the Auditor role only: no other role reads audit chains",
            audit="denied",
            who=who,
            app="contoso",
            path="/audit/chains/contoso.finance/records",
            status=403,
            reason="target_out_of_scope",
        )
    yield ApiCase(
        id="api.priv.auditor-config",
        why="Auditor has no config.manage",
        audit="denied",
        who=AUDITOR_C_FIN,
        app="contoso",
        path="/d/config",
        status=403,
        reason="permission_missing",
    )
    yield ApiCase(
        id="api.priv.auditor-foreign-app",
        why="a fabrikam Auditor token presented to the contoso audit router is rejected",
        audit="none",
        gap=GAP_NO_SCOPE,
        who=p("fabrikam", "finance", Role.SECURITY_AUDITOR),
        app="contoso",
        path="/audit/chains/fabrikam.finance/records",
        status=401,
        reason="unknown_kid",
    )


def _priv_scenarios() -> Iterator[ScenarioCase]:
    yield ScenarioCase(
        id="api.priv.auditor-expired-grant",
        kind="api",
        why="after the grant expires (fake clock) the same read is denied",
        audit="denied",
        scenario="api_expired_grant",
        who=AUDITOR_C_OPS,
    )
    yield ScenarioCase(
        id="api.priv.privileged-roles-are-time-bound",
        kind="api",
        why="an expired Admin/Auditor role assignment stops conferring permissions",
        audit="denied",
        scenario="role_expiry",
        who=ADMIN_C_FIN,
    )


def build_cases() -> dict[str, list[Any]]:
    """All rows grouped by path kind."""
    api: list[Any] = [
        *_api_domain_matrix(),
        *_api_resource_matrix(),
        *_api_token_replay(),
        *_api_unauth(),
        *_api_forged(),
        *_api_config(),
        *[replace(c, world="grant") for c in _api_privileged()],
    ]
    search: list[Any] = [*_search_matrix(), *_search_refused(), *_search_privileged()]
    export: list[Any] = [*_export_matrix(), *_export_resource_and_empty(), *_export_privileged()]
    scenarios = [
        *_cache_pairs(),
        *_cache_special(),
        *_cache_priv(),
        *_cache_fanout(),
        *_push_matrix(),
        *_push_special(),
        *_lifecycle(),
        *_priv_scenarios(),
    ]
    out: dict[str, list[Any]] = {
        "api": api,
        "search": search,
        "export": export,
        "cache": [],
        "push": [],
    }
    for row in scenarios:
        out[row.kind].append(row)
    return out


CASES: Final = build_cases()
API_CASES: Final[list[ApiCase]] = [c for c in CASES["api"] if isinstance(c, ApiCase)]
SEARCH_CASES: Final[list[SearchCase]] = [c for c in CASES["search"] if isinstance(c, SearchCase)]
EXPORT_CASES: Final[list[ExportCase]] = [c for c in CASES["export"] if isinstance(c, ExportCase)]


def scenario_cases(
    kind: Kind, prefix_scenarios: tuple[str, ...] | None = None
) -> list[ScenarioCase]:
    return [
        c
        for c in CASES[kind]
        if isinstance(c, ScenarioCase)
        and (prefix_scenarios is None or c.scenario.split(":")[0] in prefix_scenarios)
    ]


def all_rows() -> list[CaseBase]:
    return [row for kind in KINDS for row in CASES[kind]]
