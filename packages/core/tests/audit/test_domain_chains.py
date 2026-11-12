"""PRP-31 item 14b: the shared, source-qualified per-domain audit chain id.

Proves: catalog chains are byte-identical to the pre-14b form; every other source round-trips
to exactly its domain; the encoding is injective (no two domain ids share a chain, even with
``.``, ``-`` and ``_`` in every segment); legacy and qualified forms never cross; every output
fits the ``AuditRecord`` ``chain_id`` pattern; the writer raises and the reader returns ``None``
on anything that is not an exact encoding.
"""

from __future__ import annotations

import itertools
import re

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from neurosphere_core.audit import (
    domain_audit_chain_id,
    domain_from_audit_chain,
    validate_chain_id,
)
from neurosphere_core.audit.repository import CHAIN_ID_PATTERN
from neurosphere_core.errors import InvalidSchemaError

CHAIN = re.compile(r"^[a-z0-9][a-z0-9._-]{0,127}$")
CLOUDS = ("commercial", "government")

_HEAD = "abz09"
_TAIL = "abz09._-"


def _dom(cloud: str, customer: str, source: str, name: str) -> str:
    return f"{cloud}:{customer}:{source}:domain:{name}"


# Segments that begin with [a-z0-9] and may contain '.', '_' and '-' anywhere after that.
segment = st.builds(
    lambda head, tail: head + tail,
    st.sampled_from("abcdefghijklmnopqrstuvwxyz0123456789"),
    st.text(alphabet="abcdefghijklmnopqrstuvwxyz0123456789._-", max_size=24),
)
customer = st.builds(
    lambda head, tail: head + tail,
    st.sampled_from("abcdefghijklmnopqrstuvwxyz0123456789"),
    st.text(alphabet="abcdefghijklmnopqrstuvwxyz0123456789_-", max_size=16),
)


# ------------------------------------------------------------------------------- the format


def test_catalog_chain_is_byte_identical_to_the_legacy_form() -> None:
    for cust, name in [("contoso", "finance"), ("contoso", "a.b-c_d"), ("c-1_x", "dom-001")]:
        domain = _dom("commercial", cust, "catalog", name)
        legacy = f"{cust}.{domain.rsplit(':', 1)[-1]}"  # what every writer emitted before 14b
        assert domain_audit_chain_id(cust, domain) == legacy


@pytest.mark.parametrize(
    ("domain", "chain"),
    [
        ("commercial:contoso:sandbox:domain:dom-001", "contoso._7.sandbox.dom-001"),
        (
            "commercial:contoso:neurosphere:domain:customer-control",
            "contoso._11.neurosphere.customer-control",
        ),
        ("commercial:contoso:billing:domain:finance", "contoso._7.billing.finance"),
        ("government:contoso:a.b:domain:c", "contoso._3.a.b.c"),
    ],
)
def test_non_catalog_format(domain: str, chain: str) -> None:
    customer_id = domain.split(":")[1]
    assert domain_audit_chain_id(customer_id, domain) == chain
    assert domain_from_audit_chain(domain.split(":")[0], customer_id, chain) == domain


@pytest.mark.parametrize("source", ["catalog", "sandbox", "neurosphere"])
@pytest.mark.parametrize("cloud", CLOUDS)
def test_three_sources_round_trip(cloud: str, source: str) -> None:
    domain = _dom(cloud, "contoso", source, "dom-001")
    chain = domain_audit_chain_id("contoso", domain)
    assert validate_chain_id(chain) == chain
    assert domain_from_audit_chain(cloud, "contoso", chain) == domain


def test_same_name_different_source_gets_different_chains() -> None:
    names = {
        domain_audit_chain_id("contoso", _dom("commercial", "contoso", source, "finance"))
        for source in ("catalog", "billing", "sandbox", "neurosphere", "catalog.x", "x.catalog")
    }
    assert len(names) == 6


def test_dotted_segments_that_would_alias_naively_stay_distinct() -> None:
    # A plain '.'-join would map all three to 'contoso.a.b.c'.
    pairs = [("a", "b.c"), ("a.b", "c"), ("a.b.c", "x")]
    chains = [
        domain_audit_chain_id("contoso", _dom("commercial", "contoso", s, n)) for s, n in pairs
    ]
    assert len(set(chains)) == 3
    for (s, n), chain in zip(pairs, chains, strict=True):
        assert domain_from_audit_chain("commercial", "contoso", chain) == _dom(
            "commercial", "contoso", s, n
        )


# ------------------------------------------------------------------------- property tests


@settings(max_examples=400, deadline=None)
@given(cloud=st.sampled_from(CLOUDS), cust=customer, source=segment, name=segment)
def test_round_trip_property(cloud: str, cust: str, source: str, name: str) -> None:
    domain = _dom(cloud, cust, source, name)
    try:
        chain = domain_audit_chain_id(cust, domain)
    except InvalidSchemaError:
        # Only refusal: the id would exceed the 128-character chain limit.
        legacy_len = len(cust) + 1 + len(name)
        qualified_len = legacy_len + 2 + len(str(len(source))) + len(source) + 1
        assert (legacy_len if source == "catalog" else qualified_len) > 128
        return
    assert CHAIN.fullmatch(chain)
    assert CHAIN_ID_PATTERN.fullmatch(chain)
    assert domain_from_audit_chain(cloud, cust, chain) == domain
    other_cloud = "government" if cloud == "commercial" else "commercial"
    # The chain carries no cloud: the reader takes it from the scope (one cloud per deployment).
    assert domain_from_audit_chain(other_cloud, cust, chain) == _dom(
        other_cloud, cust, source, name
    )


@settings(max_examples=400, deadline=None)
@given(cust=customer, a=st.tuples(segment, segment), b=st.tuples(segment, segment))
def test_injective_property(cust: str, a: tuple[str, str], b: tuple[str, str]) -> None:
    da = _dom("commercial", cust, *a)
    db = _dom("commercial", cust, *b)
    try:
        ca = domain_audit_chain_id(cust, da)
        cb = domain_audit_chain_id(cust, db)
    except InvalidSchemaError:
        return
    assert (ca == cb) == (da == db)


@settings(max_examples=300, deadline=None)
@given(cust=customer, rest=st.text(alphabet="abz019._-", min_size=0, max_size=30))
def test_inverse_accepts_only_exact_encodings(cust: str, rest: str) -> None:
    chain = f"{cust}.{rest}"
    domain = domain_from_audit_chain("commercial", cust, chain)
    if domain is not None:
        assert domain_audit_chain_id(cust, domain) == chain


def test_exhaustive_small_alphabet_is_injective() -> None:
    segs = [
        h + "".join(t)
        for h in _HEAD[:3]
        for n in range(3)
        for t in itertools.product(_TAIL, repeat=n)
    ]
    seen: dict[str, str] = {}
    for source, name in itertools.product(["catalog", *segs], segs):
        domain = _dom("commercial", "c", source, name)
        chain = domain_audit_chain_id("c", domain)
        assert chain not in seen, (chain, seen.get(chain), domain)
        seen[chain] = domain
        assert domain_from_audit_chain("commercial", "c", chain) == domain
    assert len(seen) > 10_000


# -------------------------------------------------------- legacy and qualified never cross


def test_marker_cannot_start_a_catalog_name() -> None:
    # The writer refuses a catalog name that does not start with [a-z0-9] (the reader already did).
    with pytest.raises(InvalidSchemaError):
        domain_audit_chain_id("contoso", _dom("commercial", "contoso", "catalog", "_7.sandbox.x"))


def test_a_qualified_chain_never_parses_as_catalog_and_vice_versa() -> None:
    qualified = domain_audit_chain_id("contoso", _dom("commercial", "contoso", "sandbox", "x"))
    parsed = domain_from_audit_chain("commercial", "contoso", qualified)
    assert parsed is not None
    assert ":catalog:" not in parsed
    legacy = "contoso.dom-001"
    assert domain_from_audit_chain("commercial", "contoso", legacy) == _dom(
        "commercial", "contoso", "catalog", "dom-001"
    )


@pytest.mark.parametrize(
    "chain",
    [
        "contoso._7.catalog.finance",  # catalog spelled in qualified form: not canonical
        "contoso._07.sandbox.x",  # leading zero
        "contoso._0..x",  # empty source
        "contoso._8.sandbox.x",  # wrong length
        "contoso._6.sandbox.x",
        "contoso._7.sandbox.",  # empty name
        "contoso._7.sandbox",  # no name
        "contoso._7sandbox.x",  # no separator
        "contoso._x.sandbox.x",
        "contoso._",
        "contoso._.x",
        "contoso.-x",
        "contoso..x",
        "contoso._7._andbox.x",  # source must start with [a-z0-9]
        "contoso._7.sandbox._x",  # name must start with [a-z0-9]
        "contoso",
        "contoso.",
        "contosox.finance",
        "fabrikam.finance",
        "contoso.Finance",
        "contoso.fin/ance",
        "Contoso.finance",
        "",
    ],
)
def test_inverse_rejects_non_encodings(chain: str) -> None:
    assert domain_from_audit_chain("commercial", "contoso", chain) is None


@pytest.mark.parametrize(
    ("cloud", "customer_id"),
    [("azure", "contoso"), ("", "contoso"), ("commercial", "con.toso"), ("commercial", "")],
)
def test_inverse_rejects_bad_scope_values(cloud: str, customer_id: str) -> None:
    assert domain_from_audit_chain(cloud, customer_id, f"{customer_id}.finance") is None


# ------------------------------------------------------------------------- writer refusals


@pytest.mark.parametrize(
    ("customer_id", "domain"),
    [
        ("contoso", "commercial:fabrikam:catalog:domain:finance"),  # another customer
        ("contoso", "azure:contoso:catalog:domain:finance"),  # unknown cloud
        ("contoso", "commercial:contoso:catalog:agent:finance"),  # not a domain id
        ("contoso", "commercial:contoso:catalog:domain"),  # too few segments
        ("contoso", "commercial:contoso:catalog:domain:a:b"),  # too many
        ("contoso", "commercial:contoso:catalog:domain:fin/ance"),  # legal name, illegal chain
        ("contoso", "commercial:contoso:catalog:domain:a=b"),
        ("contoso", "commercial:contoso:catalog:domain:-x"),
        ("contoso", "commercial:contoso:catalog:domain:"),
        ("contoso", "commercial:contoso:Sandbox:domain:x"),
        ("contoso", "commercial:contoso:-s:domain:x"),
        ("con.toso", "commercial:con.toso:catalog:domain:x"),  # dotted customer: would collide
        ("-contoso", "commercial:-contoso:catalog:domain:x"),
        ("contoso", "commercial:contoso:catalog:domain:" + "a" * 121),  # 129 chars: too long
        ("contoso", "commercial:contoso:sandbox:domain:" + "a" * 110),
        ("contoso", "contoso.finance"),
    ],
)
def test_writer_refuses_unencodable_ids(customer_id: str, domain: str) -> None:
    with pytest.raises(InvalidSchemaError) as info:
        domain_audit_chain_id(customer_id, domain)
    assert info.value.reason == "invalid_chain_id"


def test_dotted_customers_would_collide_so_they_are_refused() -> None:
    # 'a.b' + catalog 'c' and 'a' + catalog 'b.c' would both be 'a.b.c'.
    assert domain_audit_chain_id("a", _dom("commercial", "a", "catalog", "b.c")) == "a.b.c"
    with pytest.raises(InvalidSchemaError):
        domain_audit_chain_id("a.b", _dom("commercial", "a.b", "catalog", "c"))
