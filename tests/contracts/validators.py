"""Cross-field contract rules that JSON Schema 2020-12 cannot express (PRP-01 item 7).

Schema ``description`` texts name each rule by function (``validate_*`` / ``check_*``);
test_validators.py greps the schemas and fails if a named function is missing here.

Conventions:

* Every validator returns a list of human-readable problems; an empty list means "passes".
* Validators never raise on malformed input: shape errors are JSON Schema's job, so a
  missing or mistyped member is skipped rather than reported twice.
* Anchored patterns are checked with ``re.fullmatch``. Python ``re.search``/``re.match`` let
  ``$`` match before a trailing newline (ADR-0004), which is how the ``jsonschema`` library
  evaluates ``pattern``; these validators close that gap.
* Timestamps in these contracts are RFC 3339 UTC with a ``Z`` suffix and up to nine
  fractional digits; they are compared as integer tuples, so no precision is lost.
"""

from __future__ import annotations

import itertools
import math
import re
from collections import Counter
from collections.abc import Callable, Iterable, Mapping, Sequence
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from contract_support import jcs, sha256_jcs

Problems = list[str]
Doc = Mapping[str, Any]

# --------------------------------------------------------------------------- primitives

CANONICAL_ID_PATTERN = (
    r"^(commercial|government):[a-z0-9._-]+:[a-z0-9._-]+:[a-z0-9._-]+:[a-z0-9._/=-]+$"
)
CANONICAL_ID_RE = re.compile(CANONICAL_ID_PATTERN)
CLOUD_PREFIXES = ("commercial:", "government:")
CANONICAL_ID_MAX_LENGTH = 512
CANONICAL_ID_MIN_LENGTH = 9

_TS_RE = re.compile(
    r"(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.(\d{1,9}))?Z",
)


def canonical_id_fullmatches(value: object, pattern: str = CANONICAL_ID_PATTERN) -> bool:
    return (
        isinstance(value, str)
        and CANONICAL_ID_MIN_LENGTH <= len(value) <= CANONICAL_ID_MAX_LENGTH
        and re.fullmatch(pattern, value) is not None
    )


def id_segments(value: str) -> list[str]:
    """``cloud:customer:source:type:id`` -> five segments (the id may not contain ':')."""
    return value.split(":")


def ts_key(value: object) -> tuple[int, ...] | None:
    """Sortable key for an RFC 3339 UTC timestamp, or None when it is not one."""
    if not isinstance(value, str):
        return None
    match = _TS_RE.fullmatch(value)
    if match is None:
        return None
    *whole, fraction = match.groups()
    nanos = int((fraction or "").ljust(9, "0"))
    return (*(int(part) for part in whole), nanos)


def _date(value: object) -> date | None:
    if not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _decimal(value: object) -> Decimal | None:
    if not isinstance(value, str):
        return None
    try:
        result = Decimal(value)
    except InvalidOperation:
        return None
    return result if result.is_finite() else None


def _number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return float(value)


def _mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _list(value: object) -> list[Any]:
    return value if isinstance(value, list) else []


def iter_canonical_ids(node: object, path: str = "") -> Iterable[tuple[str, str]]:
    """``(json pointer, value)`` for every string that claims to be a canonical ID.

    A string claims to be one when it starts with ``commercial:`` or ``government:``.
    Evidence identifiers are opaque (they may legitimately use other casing) and are
    skipped, as is the free-form ``alias_value``.
    """
    if isinstance(node, Mapping):
        for key, value in node.items():
            if "evidence" in key or key == "alias_value":
                continue
            yield from iter_canonical_ids(value, f"{path}/{key}")
    elif isinstance(node, list):
        for i, value in enumerate(node):
            yield from iter_canonical_ids(value, f"{path}/{i}")
    elif isinstance(node, str) and node.startswith(CLOUD_PREFIXES):
        yield path, node


# --------------------------------------------------------------------------- catalog


def validate_canonical_id_fullmatch(doc: object) -> Problems:
    """Every canonical ID in the document (or the document itself) fullmatches the grammar."""
    items = [("", doc)] if isinstance(doc, str) else list(iter_canonical_ids(doc))
    return [
        f"{path or '/'}: {value!r} does not fullmatch the canonical ID grammar"
        for path, value in items
        if not canonical_id_fullmatches(value)
    ]


def validate_customer_segment_matches(doc: Doc) -> Problems:
    """The customer segment of every canonical ID equals ``customer_id``."""
    customer = doc.get("customer_id")
    if not isinstance(customer, str):
        return []
    problems = []
    for path, value in iter_canonical_ids(doc):
        segments = id_segments(value)
        if len(segments) >= 2 and segments[1] != customer:
            problems.append(f"{path}: customer segment {segments[1]!r} != {customer!r}")
    return problems


def _ordered(doc: Doc, first: str, second: str, *, strict: bool) -> Problems:
    a, b = ts_key(doc.get(first)), ts_key(doc.get(second))
    if a is None or b is None:
        return []
    if a > b or (strict and a == b):
        op = "<" if strict else "<="
        return [f"{first} {doc.get(first)!r} must be {op} {second} {doc.get(second)!r}"]
    return []


def validate_timestamp_order(doc: Doc) -> Problems:
    """created_at <= updated_at."""
    return _ordered(doc, "created_at", "updated_at", strict=False)


def validate_observation_order(doc: Doc) -> Problems:
    """first_observed <= last_observed."""
    return _ordered(doc, "first_observed", "last_observed", strict=False)


def validate_validity_interval(doc: Doc) -> Problems:
    """validity.valid_from < validity.valid_to (valid_to null means open-ended)."""
    validity = _mapping(doc.get("validity"))
    if validity.get("valid_to") is None:
        return []
    return _ordered(validity, "valid_from", "valid_to", strict=True)


def validate_security_evidence_subset(doc: Doc) -> Problems:
    """security_evidence_ids is a subset of evidence_ids."""
    evidence = set(_list(doc.get("evidence_ids")))
    missing = [e for e in _list(doc.get("security_evidence_ids")) if e not in evidence]
    return [f"security evidence {e!r} is not listed in evidence_ids" for e in missing]


def validate_override_preserves_security_evidence(previous: Doc, current: Doc) -> Problems:
    """A new version of an edge keeps every security_evidence_ids entry of the prior version.

    Applies to consecutive versions of the same edge (for example before and after an
    EdgeOverride is applied); the override document itself has no field that could remove
    evidence, which the schema guarantees with additionalProperties false.
    """
    if previous.get("id") != current.get("id"):
        return [f"different edges: {previous.get('id')!r} vs {current.get('id')!r}"]
    kept = set(_list(current.get("security_evidence_ids")))
    dropped = [e for e in _list(previous.get("security_evidence_ids")) if e not in kept]
    return [f"security evidence {e!r} was removed by the new edge version" for e in dropped]


def _decision_time(doc: Doc) -> object:
    if "decided_at" in doc:  # EdgeOverride
        return doc.get("decided_at")
    return _mapping(doc.get("curation")).get("decided_at")  # relation with curation


def validate_lock_expiry_after_decision(doc: Doc) -> Problems:
    """A held lock expires strictly after the decision that placed it."""
    lock = _mapping(doc.get("lock"))
    if lock.get("locked") is not True:
        return []
    expiry, decided = ts_key(lock.get("expiry")), ts_key(_decision_time(doc))
    if expiry is None or decided is None:
        return []
    if expiry <= decided:
        return [f"lock.expiry {lock.get('expiry')!r} is not after the decision time"]
    return []


def validate_person_id_is_pseudonym(doc: Doc) -> Problems:
    """The id segment of a Person canonical ID equals principal_pseudonym."""
    value, pseudonym = doc.get("id"), doc.get("principal_pseudonym")
    if not isinstance(value, str) or not isinstance(pseudonym, str):
        return []
    segments = id_segments(value)
    if len(segments) == 5 and segments[4] != pseudonym:
        return [f"id segment {segments[4]!r} != principal_pseudonym {pseudonym!r}"]
    return []


def validate_alias_type_matches(doc: Doc) -> Problems:
    """Alias entity_type equals the type segment of canonical_id."""
    value, entity_type = doc.get("canonical_id"), doc.get("entity_type")
    if not isinstance(value, str) or not isinstance(entity_type, str):
        return []
    segments = id_segments(value)
    if len(segments) == 5 and segments[3] != entity_type:
        return [f"entity_type {entity_type!r} != canonical_id type segment {segments[3]!r}"]
    return []


def validate_alias_unique(aliases: Sequence[Doc]) -> Problems:
    """At most one active alias per (alias_source_id, alias_kind, alias_value)."""
    keys = Counter(
        (a.get("alias_source_id"), a.get("alias_kind"), a.get("alias_value"))
        for a in aliases
        if a.get("status") == "active"
    )
    return [f"{count} active aliases for {key!r}" for key, count in keys.items() if count > 1]


def validate_override_relation_matches_edge(doc: Doc) -> Problems:
    """EdgeOverride relation_type equals the type segment of edge_id."""
    edge_id, relation = doc.get("edge_id"), doc.get("relation_type")
    if not isinstance(edge_id, str) or not isinstance(relation, str):
        return []
    segments = id_segments(edge_id)
    if len(segments) == 5 and segments[3] != relation:
        return [f"relation_type {relation!r} != edge_id type segment {segments[3]!r}"]
    return []


def validate_supersedes_same_type(doc: Doc) -> Problems:
    """SUPERSEDES source and target share a type segment and are different IDs."""
    source, target = doc.get("source_id"), doc.get("target_id")
    if not isinstance(source, str) or not isinstance(target, str):
        return []
    problems = []
    s, t = id_segments(source), id_segments(target)
    if len(s) == 5 and len(t) == 5 and s[3] != t[3]:
        problems.append(f"source type {s[3]!r} != target type {t[3]!r}")
    if source == target:
        problems.append("an entity cannot supersede itself")
    return problems


# --------------------------------------------------------------------------- telemetry, cost


def validate_span_not_self_parent(doc: Doc) -> Problems:
    """span_id differs from parent_span_id."""
    span, parent = doc.get("span_id"), doc.get("parent_span_id")
    if span is not None and span == parent:
        return [f"span {span!r} is its own parent"]
    return []


def validate_canonical_id_grammar(doc: Doc) -> Problems:
    """canonical_agent_id, when set, passes the catalog canonical-ID grammar (fullmatch)."""
    value = doc.get("canonical_agent_id")
    if value is None or canonical_id_fullmatches(value):
        return []
    return [f"canonical_agent_id {value!r} fails the catalog canonical ID grammar"]


def validate_billing_period_order(doc: Doc) -> Problems:
    """billing_period.start_date <= billing_period.end_date (inclusive period)."""
    period = _mapping(doc.get("billing_period"))
    start, end = _date(period.get("start_date")), _date(period.get("end_date"))
    if start and end and start > end:
        return [f"billing_period start {start} is after end {end}"]
    return []


def validate_usage_window_order(doc: Doc) -> Problems:
    """usage_start <= usage_end when both are set."""
    return _ordered(doc, "usage_start", "usage_end", strict=False)


def validate_allocation_within_amount(doc: Doc) -> Problems:
    """Sum of non-null allocation components <= abs(amount)."""
    amount = _decimal(doc.get("amount"))
    allocation = _mapping(doc.get("allocation"))
    parts = [_decimal(v) for v in allocation.values() if v is not None]
    if amount is None or not parts or any(p is None for p in parts):
        return []
    total = sum((p for p in parts if p is not None), Decimal(0))
    if total > abs(amount):
        return [f"allocation total {total} exceeds abs(amount) {abs(amount)}"]
    return []


def validate_retry_amount_within_amount(doc: Doc) -> Problems:
    """retry_amount <= abs(amount)."""
    amount, retry = _decimal(doc.get("amount")), _decimal(doc.get("retry_amount"))
    if amount is not None and retry is not None and retry > abs(amount):
        return [f"retry_amount {retry} exceeds abs(amount) {abs(amount)}"]
    return []


# --------------------------------------------------------------------------- actions, audit

ACTION_STATES = (
    "drafted",
    "validated",
    "awaiting_confirmation",
    "awaiting_approval",
    "executing",
    "succeeded",
    "failed",
    "rolled_back",
    "expired",
)


def confirmation_hash(intent: Doc, hashed_fields: Sequence[str]) -> str:
    """Recompute ActionIntent.confirmation_hash per actions/v1/confirmation-hash.json."""
    return sha256_jcs({field: intent.get(field) for field in hashed_fields})


def validate_confirmation_hash(intent: Doc, definition: Doc) -> Problems:
    """confirmation_hash equals the recomputed hash (when it is set)."""
    actual = intent.get("confirmation_hash")
    if actual is None:
        return []
    fields = definition["hashed_fields"]
    missing = [f for f in fields if f not in intent]
    if missing:
        return []
    expected = confirmation_hash(intent, fields)
    if actual != expected:
        return [f"confirmation_hash {actual!r} != recomputed {expected!r}"]
    return []


def allowed_transitions(allowlist: Doc) -> frozenset[tuple[str, str]]:
    return frozenset((t["from"], t["to"]) for t in allowlist["transitions"])


def validate_state_transition(from_state: object, to_state: object, allowlist: Doc) -> Problems:
    """(from, to) is an allowlisted ActionState pair; everything else is forbidden."""
    if (from_state, to_state) not in allowed_transitions(allowlist):
        return [f"transition {from_state!r} -> {to_state!r} is not on the allowlist"]
    return []


def validate_intent_timestamps(intent: Doc) -> Problems:
    """created_at <= state_changed_at, and confirmation_expires_at > created_at."""
    problems = _ordered(intent, "created_at", "state_changed_at", strict=False)
    if intent.get("confirmation_expires_at") is not None:
        problems += _ordered(intent, "created_at", "confirmation_expires_at", strict=True)
    return problems


def validate_transition_allowlist(allowlist: Doc) -> Problems:
    """Pairs unique, no self-loops, nothing leaves a terminal state, initial state not
    terminal, every non-terminal state reachable from the initial state and able to reach a
    terminal state."""
    problems: Problems = []
    pairs = [(t.get("from"), t.get("to")) for t in _list(allowlist.get("transitions"))]
    terminal = set(_list(allowlist.get("terminal_states")))
    initial = allowlist.get("initial_state")
    for pair, count in Counter(pairs).items():
        if count > 1:
            problems.append(f"duplicate transition {pair}")
    problems += [f"self-transition {p}" for p in pairs if p[0] == p[1]]
    problems += [f"transition out of terminal state {p}" for p in pairs if p[0] in terminal]
    if initial in terminal:
        problems.append(f"initial_state {initial!r} is terminal")
    states = {s for p in pairs for s in p} | {initial} | terminal
    forward: dict[object, set[object]] = {}
    backward: dict[object, set[object]] = {}
    for a, b in pairs:
        forward.setdefault(a, set()).add(b)
        backward.setdefault(b, set()).add(a)

    def closure(start: Iterable[object], edges: Mapping[object, set[object]]) -> set[object]:
        seen, stack = set(start), list(start)
        while stack:
            for nxt in edges.get(stack.pop(), set()):
                if nxt not in seen:
                    seen.add(nxt)
                    stack.append(nxt)
        return seen

    reachable = closure([initial], forward)
    can_finish = closure(terminal, backward)
    for state in sorted(str(s) for s in states - terminal):
        if state not in {str(s) for s in reachable}:
            problems.append(f"state {state!r} is unreachable from {initial!r}")
        if state not in {str(s) for s in can_finish}:
            problems.append(f"state {state!r} cannot reach a terminal state")
    return problems


def validate_maker_checker_separation(decision: Doc) -> Problems:
    """When self_approval_allowed is false the reviewer is neither the maker nor the user
    the maker acted on behalf of."""
    if decision.get("self_approval_allowed") is not False:
        return []
    reviewer = _mapping(decision.get("reviewer")).get("principal_pseudonym")
    maker = _mapping(decision.get("maker"))
    if reviewer is None or not maker:
        return []
    problems = []
    if reviewer == maker.get("principal_pseudonym"):
        problems.append(f"reviewer {reviewer!r} is the maker (self-approval prohibited)")
    if reviewer == maker.get("on_behalf_of"):
        problems.append(f"reviewer {reviewer!r} is the user the maker acted for")
    return problems


def audit_record_hash(record: Doc) -> str:
    """sha256 over the JCS form of the record without record_hash."""
    return sha256_jcs({k: v for k, v in record.items() if k != "record_hash"})


def _sequence_key(record: Doc) -> int:
    sequence = record.get("sequence")
    return sequence if isinstance(sequence, int) else -1


def validate_audit_chain(records: Sequence[Doc], *, require_head: bool = True) -> Problems:
    """record_hash is the JCS hash of the record; per chain_id the sequence is contiguous
    (from 0 when ``require_head``) and each previous_hash equals the preceding record_hash."""
    problems: Problems = []
    chains: dict[object, list[Doc]] = {}
    for record in records:
        if record.get("record_hash") != audit_record_hash(record):
            problems.append(f"sequence {record.get('sequence')}: record_hash mismatch")
        chains.setdefault(record.get("chain_id"), []).append(record)
    for chain_id, chain in chains.items():
        chain.sort(key=_sequence_key)
        sequences = [r.get("sequence") for r in chain]
        first = 0 if require_head else sequences[0]
        if not isinstance(first, int) or sequences != list(range(first, first + len(chain))):
            problems.append(f"chain {chain_id!r}: sequence {sequences} is not contiguous")
        for prev, cur in itertools.pairwise(chain):
            if cur.get("previous_hash") != prev.get("record_hash"):
                problems.append(
                    f"chain {chain_id!r} sequence {cur.get('sequence')}: previous_hash does "
                    "not equal the preceding record_hash"
                )
    return problems


def validate_target_ref_matches_catalog_grammar(
    target_ref_schema: Doc, catalog_id_schema: Doc, corpus: Doc
) -> Problems:
    """The TargetRef canonical_id pattern agrees with the authoritative catalog grammar on
    every entry of the catalog ID corpus (fullmatch semantics)."""
    mirror = target_ref_schema["properties"]["canonical_id"]["pattern"]
    authority = catalog_id_schema["pattern"]
    problems = []
    entries = [(v, True) for v in corpus["valid"]] + [
        (e["value"], False) for e in corpus["invalid"]
    ]
    for value, expected in entries:
        got_mirror = re.fullmatch(mirror, value) is not None
        got_authority = canonical_id_fullmatches(value, authority)
        if got_authority != expected:
            problems.append(f"catalog grammar classifies {value!r} as {got_authority}")
        if got_mirror != got_authority:
            problems.append(f"TargetRef pattern and catalog grammar disagree on {value!r}")
    return problems


def validate_denial_codes_match_error_taxonomy(audit_schema: Doc, error_codes: Doc) -> Problems:
    """AuditRecord denial.code enum equals the errors/v1 taxonomy codes (same order)."""
    denial = audit_schema["$defs"]["denial"]["properties"]["code"]["enum"]
    taxonomy = [row["code"] for row in error_codes["codes"]]
    if denial != taxonomy:
        return [f"audit denial codes {denial} != error taxonomy {taxonomy}"]
    return []


# --------------------------------------------------------------------------- scope, query, chart

SCOPE_HASH_FIELDS = (
    "cloud",
    "customer_id",
    "roles",
    "allowed_domains",
    "allowed_resources",
    "policy_version",
)


def identity_scope_hash(scope: Doc) -> str:
    """sha256 over the JCS form of the hashed IdentityScope members.

    The schema lists ``principal.principal_id``; it is kept at its path (a ``principal``
    object holding only ``principal_id``), consistent with confirmation-hash.json copying
    hashed members unchanged.
    """
    projection: dict[str, Any] = {k: scope.get(k) for k in SCOPE_HASH_FIELDS}
    projection["principal"] = {"principal_id": _mapping(scope.get("principal")).get("principal_id")}
    return sha256_jcs(projection)


def check_identity_scope_hash(scope: Doc) -> Problems:
    """scope_hash equals the recomputed hash."""
    actual = scope.get("scope_hash")
    if actual is None or any(k not in scope for k in (*SCOPE_HASH_FIELDS, "principal")):
        return []
    expected = identity_scope_hash(scope)
    if actual != expected:
        return [f"scope_hash {actual!r} != recomputed {expected!r}"]
    return []


def check_identity_scope_times(scope: Doc) -> Problems:
    """expires_at > derived_at, for the scope and for every role assignment."""
    derived = scope.get("derived_at")
    problems = _ordered(scope, "derived_at", "expires_at", strict=True)
    for i, role in enumerate(_list(scope.get("roles"))):
        role_doc = {"derived_at": derived, "expires_at": _mapping(role).get("expires_at")}
        problems += [
            f"roles/{i}: {p}" for p in _ordered(role_doc, "derived_at", "expires_at", strict=True)
        ]
    return problems


def check_time_range_order(doc: Doc) -> Problems:
    """time_range.start < end (StructuredQuery) and evidence_window.start < end
    (Recommendation); both are half-open intervals."""
    problems = []
    for member in ("time_range", "evidence_window"):
        window = _mapping(doc.get(member))
        problems += [f"{member}: {p}" for p in _ordered(window, "start", "end", strict=True)]
    return problems


def _filter_bound(kind: str, value: object) -> Any:
    if kind == "money":
        return _decimal(value)
    if kind == "time":
        return ts_key(value)
    return _number(value)


_MONEY_FIELDS = frozenset({"amount", "baseline_amount", "projected_amount"})
_TIME_FIELDS = frozenset(
    {
        "event_time",
        "ingestion_time",
        "first_observed",
        "last_observed",
        "created_at",
        "updated_at",
        "completed_at",
    }
)


def check_between_order(query: Doc) -> Problems:
    """For every ``between`` filter, values [lo, hi] satisfy lo <= hi."""
    problems = []
    for i, flt in enumerate(_list(query.get("filters"))):
        flt = _mapping(flt)
        values = _list(flt.get("values"))
        if flt.get("op") != "between" or len(values) != 2:
            continue
        field = flt.get("field")
        kind = "money" if field in _MONEY_FIELDS else "time" if field in _TIME_FIELDS else "number"
        lo, hi = (_filter_bound(kind, v) for v in values)
        if lo is not None and hi is not None and lo > hi:
            problems.append(f"filters/{i}: between bounds {values} are reversed")
    return problems


# Field applicability: which allowlisted query fields make sense for which entity. This is
# the contract suite's reading of NS-06; PRP-05 (query planner) owns the executable matrix
# and may only narrow it. Catalog entities share one vocabulary because neighbors and
# impact_paths queries filter on edge members (confidence, relation_status, locked).
_ALL_ID_FIELDS = frozenset(
    {
        "id",
        "agent_id",
        "agent_version_id",
        "model_deployment_id",
        "owner_id",
        "domain_id",
        "source_id",
        "tool_id",
        "service_id",
        "policy_id",
        "subject_id",
        "principal_id",
    }
)
_CATALOG_FIELDS = _ALL_ID_FIELDS | {
    "cloud",
    "lifecycle_status",
    "classification",
    "status",
    "kind",
    "relation_status",
    "provider",
    "model_name",
    "model_version",
    "environment",
    "confidence",
    "first_observed",
    "last_observed",
    "created_at",
    "updated_at",
    "locked",
    "has_owner",
}
_RECOMMENDATION_EXTRA = frozenset({"score", "baseline_amount", "projected_amount", "advisory"})
_TOKEN_FIELDS = frozenset(
    {"input_tokens", "output_tokens", "cached_tokens", "reasoning_tokens", "total_tokens"}
)
FIELD_APPLICABILITY: Mapping[str, frozenset[str]] = {
    **{
        entity: frozenset(_CATALOG_FIELDS)
        for entity in (
            "person",
            "agent",
            "agent_version",
            "model_deployment",
            "grounding_source",
            "tool",
            "service",
            "domain",
            "owner",
            "policy",
            "run_reference",
        )
    },
    "recommendation": frozenset(_CATALOG_FIELDS | _RECOMMENDATION_EXTRA),
    "telemetry_event": frozenset(
        (_ALL_ID_FIELDS - {"owner_id", "policy_id", "subject_id"})
        | _TOKEN_FIELDS
        | {
            "cloud",
            "environment",
            "provider",
            "model_name",
            "model_version",
            "outcome",
            "span_kind",
            "classification",
            "duration_ms",
            "retries",
            "error_rate",
            "latency_p50_ms",
            "latency_p95_ms",
            "request_count",
            "event_time",
            "ingestion_time",
        }
    ),
    "cost_record": frozenset(
        {
            "id",
            "agent_id",
            "agent_version_id",
            "model_deployment_id",
            "owner_id",
            "domain_id",
            "source_id",
            "service_id",
            "cloud",
            "provider",
            "model_name",
            "model_version",
            "kind",
            "observation_source",
            "currency",
            "status",
            "retries",
            "amount",
            "event_time",
            "created_at",
        }
        | _TOKEN_FIELDS
    ),
    "evaluation_result": frozenset(
        {
            "id",
            "subject_id",
            "agent_id",
            "agent_version_id",
            "model_deployment_id",
            "domain_id",
            "source_id",
            "cloud",
            "environment",
            "status",
            "kind",
            "score",
            "request_count",
            "created_at",
            "completed_at",
        }
    ),
}


def check_structured_query_field_applicability(query: Doc) -> Problems:
    """Every referenced field (filters, fields, sort, group_by, aggregations) applies to
    the queried entity. Sort keys may also name an aggregation alias (``as``)."""
    entity = query.get("entity")
    allowed = FIELD_APPLICABILITY.get(entity) if isinstance(entity, str) else None
    if allowed is None:
        return []
    aliases = {_mapping(a).get("as") for a in _list(query.get("aggregations"))}
    refs: list[tuple[str, object]] = []
    refs += [
        (f"filters/{i}", _mapping(f).get("field"))
        for i, f in enumerate(_list(query.get("filters")))
    ]
    refs += [(f"fields/{i}", f) for i, f in enumerate(_list(query.get("fields")))]
    refs += [(f"group_by/{i}", f) for i, f in enumerate(_list(query.get("group_by")))]
    refs += [
        (f"aggregations/{i}", _mapping(a).get("field"))
        for i, a in enumerate(_list(query.get("aggregations")))
        if _mapping(a).get("field") is not None
    ]
    refs += [
        (f"sort/{i}", _mapping(s).get("field"))
        for i, s in enumerate(_list(query.get("sort")))
        if _mapping(s).get("field") not in aliases
    ]
    return [
        f"{where}: field {field!r} does not apply to entity {entity!r}"
        for where, field in refs
        if isinstance(field, str) and field not in allowed
    ]


def check_page_counts(page: Doc) -> Problems:
    """returned <= limit."""
    returned, limit = page.get("returned"), page.get("limit")
    if isinstance(returned, int) and isinstance(limit, int) and returned > limit:
        return [f"returned {returned} exceeds limit {limit}"]
    return []


CHART_MAX_BYTES = 2 * 1024 * 1024


def _encoding_defs(encoding: Mapping[str, Any]) -> Iterable[tuple[str, Mapping[str, Any]]]:
    for channel, definition in encoding.items():
        items = definition if isinstance(definition, list) else [definition]
        for item in items:
            yield channel, _mapping(item)


def check_chart_plan_field_references(plan: Doc) -> Problems:
    """Every encoding/transform field exists in data.values rows or is produced by an
    earlier transform (aggregate replaces the field set with groupby + outputs)."""
    spec = _mapping(plan.get("spec"))
    rows = _list(_mapping(spec.get("data")).get("values"))
    available: set[str] = {k for row in rows if isinstance(row, Mapping) for k in row}
    problems: Problems = []

    def need(field: object, where: str) -> None:
        if isinstance(field, str) and field not in available:
            problems.append(f"{where}: field {field!r} is not available")

    for i, raw in enumerate(_list(spec.get("transform"))):
        t = _mapping(raw)
        where = f"spec/transform/{i}"
        if "filter" in t:
            need(_mapping(t["filter"]).get("field"), where)
        elif "aggregate" in t:
            groupby = [g for g in _list(t.get("groupby")) if isinstance(g, str)]
            for g in groupby:
                need(g, where)
            outputs = []
            for agg in _list(t.get("aggregate")):
                agg = _mapping(agg)
                if agg.get("field") is not None:
                    need(agg.get("field"), where)
                outputs.append(agg.get("as"))
            available = set(groupby) | {o for o in outputs if isinstance(o, str)}
        elif "bin" in t or "timeUnit" in t:
            need(t.get("field"), where)
            output = t.get("as")
            if isinstance(output, str):
                available.add(output)
                if "bin" in t:
                    available.add(f"{output}_end")
        elif "fold" in t:
            for f in _list(t.get("fold")):
                need(f, where)
            names = _list(t.get("as")) or ["key", "value"]
            available.update(n for n in names if isinstance(n, str))
    for channel, definition in _encoding_defs(_mapping(spec.get("encoding"))):
        need(definition.get("field"), f"spec/encoding/{channel}")
    return problems


def check_chart_plan_mark_channels(plan: Doc) -> Problems:
    """Mark/channel compatibility: text needs a text channel; line, area and rect need x
    and y; bar and point need x or y; x2/y2 need x/y."""
    spec = _mapping(plan.get("spec"))
    mark = spec.get("mark")
    mark_type = mark if isinstance(mark, str) else _mapping(mark).get("type")
    channels = set(_mapping(spec.get("encoding")))
    problems = []
    if mark_type == "text" and "text" not in channels:
        problems.append("a text mark needs a text channel")
    if mark_type in ("line", "area", "rect") and not {"x", "y"} <= channels:
        problems.append(f"a {mark_type} mark needs both x and y")
    if mark_type in ("bar", "point") and not channels & {"x", "y"}:
        problems.append(f"a {mark_type} mark needs x or y")
    for secondary, primary in (("x2", "x"), ("y2", "y")):
        if secondary in channels and primary not in channels:
            problems.append(f"{secondary} needs {primary}")
    return problems


def check_chart_plan_size(plan: object) -> Problems:
    """Serialized document size <= 2 MiB."""
    size = len(jcs(plan).encode("utf-8"))
    if size > CHART_MAX_BYTES:
        return [f"serialized chart plan is {size} bytes (> {CHART_MAX_BYTES})"]
    return []


# --------------------------------------------------------------------------- recommendations, eval


def check_recommendation_score_interval(rec: Doc) -> Problems:
    """uncertainty.lower <= score <= uncertainty.upper when both are present."""
    score = _number(rec.get("score"))
    unc = _mapping(rec.get("uncertainty"))
    lower, upper = _number(unc.get("lower")), _number(unc.get("upper"))
    if score is None or lower is None or upper is None:
        return []
    if not lower <= score <= upper:
        return [f"score {score} is outside [{lower}, {upper}]"]
    return []


def check_recommendation_same_boundary(rec: Doc) -> Problems:
    """Every subject_ids entry and owner.owner_id has the document's cloud and customer."""
    cloud, customer = rec.get("cloud"), rec.get("customer_id")
    ids = [(f"subject_ids/{i}", v) for i, v in enumerate(_list(rec.get("subject_ids")))]
    owner_id = _mapping(rec.get("owner")).get("owner_id")
    if owner_id is not None:
        ids.append(("owner/owner_id", owner_id))
    problems = []
    for where, value in ids:
        if not isinstance(value, str):
            continue
        segments = id_segments(value)
        if len(segments) < 2:
            continue
        if segments[0] != cloud or segments[1] != customer:
            problems.append(f"{where}: {value!r} is outside {cloud}:{customer}")
    return problems


def check_evaluation_times(result: Doc) -> Problems:
    """started_at <= completed_at and sampling.window.start < sampling.window.end."""
    problems = _ordered(result, "started_at", "completed_at", strict=False)
    window = _mapping(_mapping(result.get("sampling")).get("window"))
    problems += [f"sampling.window: {p}" for p in _ordered(window, "start", "end", strict=True)]
    return problems


def check_evaluation_score_scale(result: Doc) -> Problems:
    """score.value and uncertainty bounds lie within score.scale [min, max]."""
    problems = []
    for i, raw in enumerate(_list(result.get("scores"))):
        score = _mapping(raw)
        scale = _mapping(score.get("scale"))
        lo, hi = _number(scale.get("min")), _number(scale.get("max"))
        if lo is None or hi is None:
            continue
        unc = _mapping(score.get("uncertainty"))
        for name, value in (
            ("value", score.get("value")),
            ("uncertainty.lower", unc.get("lower")),
            ("uncertainty.upper", unc.get("upper")),
        ):
            number = _number(value)
            if number is not None and not lo <= number <= hi:
                problems.append(f"scores/{i}: {name} {number} is outside scale [{lo}, {hi}]")
    return problems


def check_evaluation_sampling_counts(result: Doc) -> Problems:
    """sampling.sample_size <= sampling.population_size when the population is known."""
    sampling = _mapping(result.get("sampling"))
    sample, population = sampling.get("sample_size"), sampling.get("population_size")
    if isinstance(sample, int) and isinstance(population, int) and sample > population:
        return [f"sample_size {sample} exceeds population_size {population}"]
    return []


# --------------------------------------------------------------------------- deployment, connectors


def check_deployment_manifest(manifest: Doc) -> Problems:
    """Each service appears at most once; existing_resource_id is not repeated across
    services (ARM IDs compare case-insensitively)."""
    services = [_mapping(s) for s in _list(manifest.get("services"))]
    problems = [
        f"service {name!r} appears {count} times"
        for name, count in Counter(s.get("service") for s in services).items()
        if count > 1
    ]
    resource_ids = Counter(
        s["existing_resource_id"].casefold()
        for s in services
        if isinstance(s.get("existing_resource_id"), str)
    )
    problems += [
        f"existing_resource_id {rid!r} is used by {count} services"
        for rid, count in resource_ids.items()
        if count > 1
    ]
    return problems


def check_capability_matrix(entries: Sequence[Doc], today: date | None = None) -> Problems:
    """(service, feature, cloud, region, sku) is unique across a matrix; observed_on is not
    in the future (UTC)."""
    today = today or datetime.now(UTC).date()
    keys = Counter(
        (e.get("service"), e.get("feature"), e.get("cloud"), e.get("region"), e.get("sku"))
        for e in entries
    )
    problems = [f"duplicate capability row {key}" for key, count in keys.items() if count > 1]
    for e in entries:
        observed = _date(e.get("observed_on"))
        if observed is not None and observed > today:
            problems.append(f"observed_on {observed} is in the future (today {today})")
    return problems


VAULT_HOST_CLOUD = {"vault.azure.net": "commercial", "vault.usgovcloudapi.net": "government"}
# Prefixes of well-known credential formats. Matched case-sensitively at the start of the
# whole value or of any '/'- or ':'-separated piece.
SECRET_PREFIXES = (
    "ghp_",
    "gho_",
    "ghu_",
    "ghs_",
    "ghr_",
    "github_pat_",
    "glpat-",
    "xoxb-",
    "xoxp-",
    "xoxa-",
    "sk-",
    "AKIA",
    "ASIA",
    "AIza",
    "eyJ",
)
ENTROPY_MIN_LENGTH = 20
ENTROPY_THRESHOLD = 3.5


def shannon_entropy(text: str) -> float:
    if not text:
        return 0.0
    counts = Counter(text)
    return -sum(n / len(text) * math.log2(n / len(text)) for n in counts.values())


def looks_like_secret(value: str) -> bool:
    pieces = [value, *re.split(r"[/:]", value)]
    if any(piece.startswith(SECRET_PREFIXES) for piece in pieces):
        return True
    for chunk in re.split(r"[._:/-]", value):
        if (
            len(chunk) >= ENTROPY_MIN_LENGTH
            and re.search(r"[0-9]", chunk)
            and re.search(r"[A-Za-z]", chunk)
            and shannon_entropy(chunk) >= ENTROPY_THRESHOLD
        ):
            return True
    return False


def check_connector_manifest(manifest: Doc) -> Problems:
    """credential_refs names are unique; no scope or name carries secret-like material
    (known credential prefixes or a high-entropy run); every vault_ref host belongs to a
    cloud listed in supported_clouds."""
    refs = [_mapping(r) for r in _list(manifest.get("credential_refs"))]
    problems = [
        f"credential_refs name {name!r} appears {count} times"
        for name, count in Counter(r.get("name") for r in refs).items()
        if count > 1
    ]
    strings = [("name", manifest.get("name"))]
    strings += [(f"scopes/{i}", s) for i, s in enumerate(_list(manifest.get("scopes")))]
    strings += [(f"credential_refs/{i}/name", r.get("name")) for i, r in enumerate(refs)]
    problems += [
        f"{where}: value looks like secret material"
        for where, value in strings
        if isinstance(value, str) and looks_like_secret(value)
    ]
    clouds = set(_list(manifest.get("supported_clouds")))
    for i, ref in enumerate(refs):
        vault_ref = ref.get("vault_ref")
        if not isinstance(vault_ref, str):
            continue
        host = vault_ref.removeprefix("https://").split("/", 1)[0]
        cloud = next(
            (c for suffix, c in VAULT_HOST_CLOUD.items() if host.endswith("." + suffix)), None
        )
        if cloud is None:
            problems.append(f"credential_refs/{i}: vault host {host!r} is not a Key Vault host")
        elif cloud not in clouds:
            problems.append(
                f"credential_refs/{i}: {cloud} vault host but clouds are {sorted(clouds)}"
            )
    return problems


# --------------------------------------------------------------------------- registry

SingleDocValidator = Callable[[Any], Problems]

_ENTITY_VALIDATORS: tuple[SingleDocValidator, ...] = (
    validate_canonical_id_fullmatch,
    validate_customer_segment_matches,
    validate_timestamp_order,
)
_RELATION_VALIDATORS: tuple[SingleDocValidator, ...] = (
    validate_canonical_id_fullmatch,
    validate_customer_segment_matches,
    validate_observation_order,
    validate_validity_interval,
    validate_security_evidence_subset,
    validate_lock_expiry_after_decision,
)
_ENTITIES = (
    "agent",
    "agent_version",
    "domain",
    "grounding_source",
    "model_deployment",
    "owner",
    "policy",
    "recommendation_reference",
    "run_reference",
    "service",
    "tool",
)
_RELATIONS = (
    "delegates_to",
    "depends_on",
    "grounded_by",
    "invokes",
    "owned_by",
    "reads",
    "uses_model",
    "writes",
)


def single_document_validators(
    context: Mapping[str, Any],
) -> dict[str, tuple[SingleDocValidator, ...]]:
    """Validators that apply to one document of a schema, keyed by schema path.

    ``context`` supplies the data files some rules need: ``confirmation_hash`` (the
    actions/v1/confirmation-hash.json definition).
    """
    definition = context["confirmation_hash"]
    table: dict[str, tuple[SingleDocValidator, ...]] = {}
    for name in _ENTITIES:
        table[f"catalog/v1/{name}.schema.json"] = _ENTITY_VALIDATORS
    for name in _RELATIONS:
        table[f"catalog/v1/{name}.schema.json"] = _RELATION_VALIDATORS
    table.update(
        {
            "catalog/v1/person.schema.json": (*_ENTITY_VALIDATORS, validate_person_id_is_pseudonym),
            "catalog/v1/supersedes.schema.json": (
                *_RELATION_VALIDATORS,
                validate_supersedes_same_type,
            ),
            "catalog/v1/alias.schema.json": (
                validate_canonical_id_fullmatch,
                validate_customer_segment_matches,
                validate_alias_type_matches,
                lambda doc: validate_alias_unique([doc]),
            ),
            "catalog/v1/edge_override.schema.json": (
                validate_customer_segment_matches,
                validate_override_relation_matches_edge,
                validate_lock_expiry_after_decision,
            ),
            "catalog/v1/canonical_id.schema.json": (validate_canonical_id_fullmatch,),
            "telemetry/v1/telemetry-event.schema.json": (
                validate_span_not_self_parent,
                validate_canonical_id_grammar,
            ),
            "cost/v1/cost-record.schema.json": (
                validate_billing_period_order,
                validate_usage_window_order,
                validate_allocation_within_amount,
                validate_retry_amount_within_amount,
            ),
            "actions/v1/action-intent.schema.json": (
                lambda doc: validate_confirmation_hash(doc, definition),
                validate_intent_timestamps,
            ),
            "actions/v1/approval-decision.schema.json": (validate_maker_checker_separation,),
            "actions/v1/transitions.schema.json": (validate_transition_allowlist,),
            "audit/v1/audit-record.schema.json": (
                lambda doc: validate_audit_chain([doc], require_head=False),
            ),
            "scope/v1/identity-scope.schema.json": (
                check_identity_scope_hash,
                check_identity_scope_times,
            ),
            "query/v1/structured-query.schema.json": (
                check_structured_query_field_applicability,
                check_time_range_order,
                check_between_order,
            ),
            "query/v1/page.schema.json": (check_page_counts,),
            "chart/v1/chart-plan.schema.json": (
                check_chart_plan_field_references,
                check_chart_plan_mark_channels,
                check_chart_plan_size,
            ),
            "recommendations/v1/recommendation.schema.json": (
                check_time_range_order,
                check_recommendation_score_interval,
                check_recommendation_same_boundary,
            ),
            "evaluation/v1/evaluation-result.schema.json": (
                check_evaluation_times,
                check_evaluation_score_scale,
                check_evaluation_sampling_counts,
            ),
            "deployment/v1/deployment-manifest.schema.json": (check_deployment_manifest,),
            "deployment/v1/capability-matrix-entry.schema.json": (
                lambda doc: check_capability_matrix([doc]),
            ),
            "connectors/v1/connector-manifest.schema.json": (check_connector_manifest,),
        }
    )
    return table


def run_single_document_validators(
    schema: str, document: Any, context: Mapping[str, Any]
) -> Problems:
    problems: Problems = []
    for validator in single_document_validators(context).get(schema, ()):
        if isinstance(document, Mapping) or validator is validate_canonical_id_fullmatch:
            problems += validator(document)
    return problems
