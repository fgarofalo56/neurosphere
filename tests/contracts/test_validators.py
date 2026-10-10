"""Every cross-field validator named in a schema description exists and is tested.

PRP-01 gotcha: "where a rule cannot be expressed, add a Python validator in the contract
test suite and name it in the schema description. Do not silently drop the rule." The
first tests grep the schemas for ``validate_*`` / ``check_*`` names and fail when one is
missing from validators.py or never exercised by a test module; the rest mutate valid
golden examples so each rule is shown to accept the example and reject the violation.
"""

from __future__ import annotations

import copy
import re
from pathlib import Path
from typing import Any

import pytest
import validators as v
from contract_support import SCHEMA_ROOT, TESTS_DIR, iter_subschemas, load_json

NAME_RE = re.compile(r"\b(?:validate|check)_[a-z0-9_]+")
FILE_RE = re.compile(r"tests/contracts/([a-z0-9_]+\.py)")


def _named_validators() -> dict[str, set[str]]:
    """Validator name -> schema files whose description/$comment names it."""
    found: dict[str, set[str]] = {}
    for path in sorted(SCHEMA_ROOT.glob("*/v*/*.json")):
        document = load_json(path)
        texts = [
            sub.node[key]
            for sub in iter_subschemas(document)
            for key in ("description", "$comment")
            if isinstance(sub.node.get(key), str)
        ]
        # Data files (confirmation-hash.json) carry their description at the top level.
        texts += [
            document[k] for k in ("description", "$comment") if isinstance(document.get(k), str)
        ]
        for text in texts:
            for name in NAME_RE.findall(text):
                found.setdefault(name, set()).add(path.relative_to(SCHEMA_ROOT).as_posix())
    return found


def _file_claims() -> list[tuple[str, str, str]]:
    """``(schema, validator, test file)`` where a description says where a rule is checked."""
    claims = []
    for path in sorted(SCHEMA_ROOT.glob("*/v*/*.json")):
        for sub in iter_subschemas(load_json(path)):
            text = sub.node.get("description")
            if not isinstance(text, str):
                continue
            for sentence in re.split(r"(?<=[.;])\s", text):
                files = FILE_RE.findall(sentence)
                for name in NAME_RE.findall(sentence):
                    for file in files:
                        if file != "validators.py":
                            claims.append((path.name, name, file))
    return claims


NAMED = _named_validators()


def test_schemas_name_validators() -> None:
    assert len(NAMED) >= 40, sorted(NAMED)
    assert "check_id" not in NAMED  # a field name, not a validator; the grep is scoped right


@pytest.mark.parametrize("name", sorted(NAMED))
def test_named_validator_exists(name: str) -> None:
    assert callable(getattr(v, name, None)), f"{name} (named in {sorted(NAMED[name])}) is missing"


@pytest.mark.parametrize("name", sorted(NAMED))
def test_named_validator_is_exercised_by_a_test(name: str) -> None:
    pattern = re.compile(rf"\b{re.escape(name)}\b")
    users = [
        p.name
        for p in sorted(TESTS_DIR.glob("test_*.py"))
        if pattern.search(p.read_text(encoding="utf-8"))
    ]
    users = [u for u in users if u != Path(__file__).name or _called_here(name)]
    assert users, f"{name} is never exercised by a test module"


def _called_here(name: str) -> bool:
    return (
        re.search(rf"v\.{re.escape(name)}\(", Path(__file__).read_text(encoding="utf-8"))
        is not None
    )


@pytest.mark.parametrize(("schema", "name", "file"), _file_claims())
def test_description_file_references_hold(schema: str, name: str, file: str) -> None:
    """When a description says "checked by <name> in tests/contracts/<file>", that file
    exists and exercises the validator."""
    target = TESTS_DIR / file
    assert target.is_file(), f"{schema} says {name} lives in tests/contracts/{file}"
    assert name in target.read_text(encoding="utf-8"), f"{file} does not exercise {name}"


# --------------------------------------------------------------------------- helpers


def ex(rel: str) -> dict[str, Any]:
    return copy.deepcopy(load_json(SCHEMA_ROOT / rel))


RELATION = "catalog/v1/examples/valid/writes.curated-locked.json"
ENTITY = "catalog/v1/examples/valid/agent.minimal-and-typical.json"


# --------------------------------------------------------------------------- catalog


def test_validate_canonical_id_fullmatch() -> None:
    doc = ex(ENTITY)
    assert v.validate_canonical_id_fullmatch(doc) == []
    doc["domain_id"] += "\n"  # jsonschema's re.search accepts this; fullmatch does not
    assert v.validate_canonical_id_fullmatch(doc)
    assert v.validate_canonical_id_fullmatch("commercial:c:s:t:i") == []
    assert v.validate_canonical_id_fullmatch("commercial:c:s:t:i\n")
    edge = ex(RELATION)
    edge["evidence_ids"].append("commercial:NotAnId")  # evidence IDs are opaque, not checked
    assert v.validate_canonical_id_fullmatch(edge) == []


def test_validate_customer_segment_matches() -> None:
    doc = ex(ENTITY)
    assert v.validate_customer_segment_matches(doc) == []
    doc["domain_id"] = doc["domain_id"].replace(":contoso:", ":fabrikam:")
    assert v.validate_customer_segment_matches(doc)
    override = ex("catalog/v1/examples/valid/edge_override.lock.json")
    assert v.validate_customer_segment_matches(override) == []
    override["actor"] = override["actor"].replace(":contoso:", ":other:")
    assert v.validate_customer_segment_matches(override)


def test_validate_timestamp_order() -> None:
    doc = ex(ENTITY)
    assert v.validate_timestamp_order(doc) == []
    doc["created_at"], doc["updated_at"] = doc["updated_at"], doc["created_at"]
    assert v.validate_timestamp_order(doc)
    same = {"created_at": "2026-10-01T08:00:00.000000001Z", "updated_at": "2026-10-01T08:00:00Z"}
    assert v.validate_timestamp_order(same), "nanosecond precision must be kept"


def test_validate_observation_order() -> None:
    doc = ex(RELATION)
    assert v.validate_observation_order(doc) == []
    doc["first_observed"] = "2026-10-10T00:00:00Z"
    assert v.validate_observation_order(doc)


def test_validate_validity_interval() -> None:
    doc = ex(RELATION)
    assert v.validate_validity_interval(doc) == []  # valid_to null = open-ended
    doc["validity"]["valid_to"] = doc["validity"]["valid_from"]
    assert v.validate_validity_interval(doc), "valid_from < valid_to is strict"
    doc["validity"]["valid_to"] = "2027-01-01T00:00:00Z"
    assert v.validate_validity_interval(doc) == []


def test_validate_security_evidence_subset() -> None:
    doc = ex(RELATION)
    assert v.validate_security_evidence_subset(doc) == []
    doc["security_evidence_ids"].append("audit:sec-9999")
    assert v.validate_security_evidence_subset(doc)


def test_validate_override_preserves_security_evidence() -> None:
    before = ex(RELATION)
    after = copy.deepcopy(before)
    after["version"] += 1
    after["evidence_ids"].append("review:77")
    assert v.validate_override_preserves_security_evidence(before, after) == []
    after["security_evidence_ids"] = []
    assert v.validate_override_preserves_security_evidence(before, after)
    other = ex("catalog/v1/examples/valid/reads.curated-locked.json")
    assert v.validate_override_preserves_security_evidence(before, other)


def test_validate_lock_expiry_after_decision() -> None:
    edge = ex(RELATION)
    assert v.validate_lock_expiry_after_decision(edge) == []
    edge["lock"]["expiry"] = edge["curation"]["decided_at"]
    assert v.validate_lock_expiry_after_decision(edge)
    override = ex("catalog/v1/examples/valid/edge_override.lock.json")
    assert v.validate_lock_expiry_after_decision(override) == []
    override["lock"]["expiry"] = "2026-01-01T00:00:00Z"
    assert v.validate_lock_expiry_after_decision(override)
    unlocked = ex("catalog/v1/examples/valid/writes.asserted.json")
    assert v.validate_lock_expiry_after_decision(unlocked) == []


def test_validate_person_id_is_pseudonym() -> None:
    doc = ex("catalog/v1/examples/valid/person.minimal-and-typical.json")
    assert v.validate_person_id_is_pseudonym(doc) == []
    doc["principal_pseudonym"] = "psn_ffffffffffffffff"
    assert v.validate_person_id_is_pseudonym(doc)


def test_validate_alias_type_matches() -> None:
    doc = ex("catalog/v1/examples/valid/alias.external-id.json")
    assert v.validate_alias_type_matches(doc) == []
    doc["entity_type"] = "tool"
    assert v.validate_alias_type_matches(doc)


def test_validate_alias_unique() -> None:
    alias = ex("catalog/v1/examples/valid/alias.external-id.json")
    assert v.validate_alias_unique([alias]) == []
    twin = {**alias, "id": alias["id"] + "-2"}
    assert v.validate_alias_unique([alias, twin])
    assert v.validate_alias_unique([alias, {**twin, "status": "retired"}]) == []


def test_validate_override_relation_matches_edge() -> None:
    doc = ex("catalog/v1/examples/valid/edge_override.lock.json")
    assert v.validate_override_relation_matches_edge(doc) == []
    doc["relation_type"] = "writes"
    assert v.validate_override_relation_matches_edge(doc)


def test_validate_supersedes_same_type() -> None:
    doc = ex("catalog/v1/examples/valid/supersedes.asserted.json")
    assert v.validate_supersedes_same_type(doc) == []
    same = {**doc, "target_id": doc["source_id"]}
    assert v.validate_supersedes_same_type(same)
    other_type = {**doc, "target_id": "commercial:contoso:foundry:tool:x"}
    assert v.validate_supersedes_same_type(other_type)


# --------------------------------------------------------------------------- telemetry, cost


def test_validate_span_not_self_parent() -> None:
    doc = ex("telemetry/v1/examples/valid/telemetry-event.delegation.json")
    assert v.validate_span_not_self_parent(doc) == []
    doc["parent_span_id"] = doc["span_id"]
    assert v.validate_span_not_self_parent(doc)
    assert v.validate_span_not_self_parent({"span_id": None, "parent_span_id": None}) == []


def test_validate_canonical_id_grammar() -> None:
    doc = ex("telemetry/v1/examples/valid/telemetry-event.full-model-call.json")
    assert v.validate_canonical_id_grammar(doc) == []
    doc["canonical_agent_id"] = "commercial:contoso:foundry:agent:support-bot\n"
    assert v.validate_canonical_id_grammar(doc)
    doc["canonical_agent_id"] = None
    assert v.validate_canonical_id_grammar(doc) == []


def test_validate_billing_period_order() -> None:
    doc = ex("cost/v1/examples/valid/cost-record.invoiced-reconciled.json")
    assert v.validate_billing_period_order(doc) == []
    doc["billing_period"] = {"start_date": "2026-09-30", "end_date": "2026-09-01"}
    assert v.validate_billing_period_order(doc)
    doc["billing_period"] = {"start_date": "2026-09-30", "end_date": "2026-09-30"}
    assert v.validate_billing_period_order(doc) == []  # inclusive


def test_validate_usage_window_order() -> None:
    doc = ex("cost/v1/examples/valid/cost-record.estimated-full.json")
    assert v.validate_usage_window_order(doc) == []
    doc["usage_start"], doc["usage_end"] = doc["usage_end"], doc["usage_start"]
    assert v.validate_usage_window_order(doc)


def test_validate_allocation_within_amount() -> None:
    doc = ex("cost/v1/examples/valid/cost-record.invoiced-reconciled.json")
    assert v.validate_allocation_within_amount(doc) == []
    doc["allocation"]["reservation"] = "0.01"
    assert v.validate_allocation_within_amount(doc)
    credit = ex("cost/v1/examples/valid/cost-record.invoiced-credit.json")
    assert v.validate_allocation_within_amount(credit) == []  # abs(amount) for credits


def test_validate_retry_amount_within_amount() -> None:
    doc = ex("cost/v1/examples/valid/cost-record.estimated-full.json")
    assert v.validate_retry_amount_within_amount(doc) == []
    doc["retry_amount"] = "0.0124"
    assert v.validate_retry_amount_within_amount(doc)


# --------------------------------------------------------------------------- scope, query, chart


def test_check_identity_scope_hash() -> None:
    doc = ex("scope/v1/examples/valid/identity-scope.viewer.json")
    doc["scope_hash"] = v.identity_scope_hash(doc)
    assert v.check_identity_scope_hash(doc) == []
    for member, value in (
        ("allowed_domains", ["commercial:contoso:catalog:domain:hr"]),
        ("policy_version", "2026.10.01-5"),
        ("roles", []),
    ):
        assert v.check_identity_scope_hash({**doc, member: value}), member
    changed = copy.deepcopy(doc)
    changed["principal"]["principal_id"] = "commercial:contoso:entra:person:p-0000"
    assert v.check_identity_scope_hash(changed)
    # Members outside the hashed set do not change it.
    assert v.check_identity_scope_hash({**doc, "derived_at": "2026-10-10T12:05:00Z"}) == []


def test_check_identity_scope_times() -> None:
    doc = ex("scope/v1/examples/valid/identity-scope.scoped-admin.json")
    assert v.check_identity_scope_times(doc) == []
    doc["expires_at"] = doc["derived_at"]
    assert v.check_identity_scope_times(doc)
    doc = ex("scope/v1/examples/valid/identity-scope.scoped-admin.json")
    doc["roles"][-1]["expires_at"] = "2020-01-01T00:00:00Z"
    assert any(p.startswith("roles/") for p in v.check_identity_scope_times(doc))


def test_check_time_range_order() -> None:
    query = ex("query/v1/examples/valid/structured-query.aggregate-cost-by-day.json")
    assert v.check_time_range_order(query) == []
    query["time_range"]["end"] = query["time_range"]["start"]
    assert v.check_time_range_order(query), "half-open: start == end is empty"
    rec = ex("recommendations/v1/examples/valid/recommendation.cost-spike-scored.json")
    assert v.check_time_range_order(rec) == []
    window = rec["evidence_window"]
    window["start"], window["end"] = window["end"], window["start"]
    assert v.check_time_range_order(rec)


def test_check_between_order() -> None:
    query = ex("query/v1/examples/valid/structured-query.aggregate-cost-by-day.json")
    assert v.check_between_order(query) == []
    query["filters"] = [
        {"field": "amount", "op": "between", "values": ["10.00", "9.5"]},
        {"field": "duration_ms", "op": "between", "values": [5, 10]},
        {
            "field": "event_time",
            "op": "between",
            "values": ["2026-10-02T00:00:00Z", "2026-10-01T00:00:00Z"],
        },
    ]
    problems = v.check_between_order(query)
    assert [p.split(":")[0] for p in problems] == ["filters/0", "filters/2"]


def test_check_structured_query_field_applicability() -> None:
    for name in ("list-agents", "aggregate-cost-by-day", "neighbors"):
        query = ex(f"query/v1/examples/valid/structured-query.{name}.json")
        assert v.check_structured_query_field_applicability(query) == [], name
    cost = ex("query/v1/examples/valid/structured-query.aggregate-cost-by-day.json")
    cost["filters"].append({"field": "span_kind", "op": "eq", "value": "retry"})
    assert v.check_structured_query_field_applicability(cost)
    agents = ex("query/v1/examples/valid/structured-query.list-agents.json")
    agents["fields"].append("event_time")
    assert v.check_structured_query_field_applicability(agents)
    agents = ex("query/v1/examples/valid/structured-query.list-agents.json")
    agents["sort"] = [{"field": "amount", "direction": "desc"}]
    assert v.check_structured_query_field_applicability(agents)
    assert set(v.FIELD_APPLICABILITY) == {
        "person", "agent", "agent_version", "model_deployment", "grounding_source", "tool",
        "service", "domain", "owner", "policy", "recommendation", "run_reference",
        "telemetry_event", "cost_record", "evaluation_result",
    }  # fmt: skip


def test_field_applicability_uses_only_allowlisted_fields() -> None:
    defs = load_json(SCHEMA_ROOT / "query/v1/structured-query.schema.json")["$defs"]
    allowlisted = {
        value
        for name in (
            "id_field",
            "keyword_field",
            "number_field",
            "money_field",
            "time_field",
            "boolean_field",
        )
        for value in defs[name]["enum"]
    }
    entities = set(defs["catalog_entity"]["enum"]) | set(defs["entity"]["anyOf"][1]["enum"])
    assert set(v.FIELD_APPLICABILITY) == entities
    for entity, fields in v.FIELD_APPLICABILITY.items():
        assert fields <= allowlisted, (entity, sorted(fields - allowlisted))
    covered = set().union(*v.FIELD_APPLICABILITY.values())
    assert covered == allowlisted, sorted(allowlisted - covered)


def test_check_page_counts() -> None:
    page = ex("query/v1/examples/valid/page.truncated.json")
    assert v.check_page_counts(page) == []
    page["returned"] = page["limit"] + 1
    assert v.check_page_counts(page)


def test_check_chart_plan_field_references() -> None:
    for name in ("bar-cost-by-agent", "line-latency-transforms"):
        plan = ex(f"chart/v1/examples/valid/chart-plan.{name}.json")
        assert v.check_chart_plan_field_references(plan) == [], name
    plan = ex("chart/v1/examples/valid/chart-plan.line-latency-transforms.json")
    plan["spec"]["encoding"]["y"]["field"] = "p95_ms"  # consumed by the aggregate transform
    assert v.check_chart_plan_field_references(plan)
    plan = ex("chart/v1/examples/valid/chart-plan.bar-cost-by-agent.json")
    plan["spec"]["encoding"]["x"]["field"] = "no_such_column"
    assert v.check_chart_plan_field_references(plan)
    folded = {
        "spec": {
            "data": {"values": [{"a": 1, "b": 2}]},
            "transform": [{"fold": ["a", "b"]}, {"bin": True, "field": "value", "as": "v_bin"}],
            "encoding": {
                "x": {"field": "v_bin"},
                "x2": {"field": "v_bin_end"},
                "color": {"field": "key"},
            },
        }
    }
    assert v.check_chart_plan_field_references(folded) == []


def test_check_chart_plan_mark_channels() -> None:
    plan = ex("chart/v1/examples/valid/chart-plan.bar-cost-by-agent.json")
    assert v.check_chart_plan_mark_channels(plan) == []
    plan["spec"]["mark"] = "text"
    assert v.check_chart_plan_mark_channels(plan)
    line = ex("chart/v1/examples/valid/chart-plan.line-latency-transforms.json")
    assert v.check_chart_plan_mark_channels(line) == []
    del line["spec"]["encoding"]["y"]
    assert v.check_chart_plan_mark_channels(line)
    assert v.check_chart_plan_mark_channels(
        {"spec": {"mark": "bar", "encoding": {"y": {}, "x2": {}}}}
    )


def test_check_chart_plan_size() -> None:
    plan = ex("chart/v1/examples/valid/chart-plan.bar-cost-by-agent.json")
    assert v.check_chart_plan_size(plan) == []
    plan["spec"]["data"]["values"] = [{"label": "x" * 1024}] * 2100
    assert v.check_chart_plan_size(plan)


# --------------------------------------------------------------------------- recommendations, eval


def test_check_recommendation_score_interval() -> None:
    rec = ex("recommendations/v1/examples/valid/recommendation.cost-spike-scored.json")
    assert v.check_recommendation_score_interval(rec) == []
    rec["score"] = rec["uncertainty"]["upper"] + 0.5
    assert v.check_recommendation_score_interval(rec)
    cold = ex("recommendations/v1/examples/valid/recommendation.cold-start-unused-agent.json")
    assert v.check_recommendation_score_interval(cold) == []


def test_check_recommendation_same_boundary() -> None:
    rec = ex("recommendations/v1/examples/valid/recommendation.cost-spike-scored.json")
    assert v.check_recommendation_same_boundary(rec) == []
    rec["subject_ids"].append(rec["subject_ids"][0].replace("commercial:", "government:", 1))
    assert v.check_recommendation_same_boundary(rec)
    rec = ex("recommendations/v1/examples/valid/recommendation.cost-spike-scored.json")
    rec["owner"] = {"resolution": "assigned", "owner_id": "commercial:other:neurosphere:owner:x"}
    assert v.check_recommendation_same_boundary(rec) == [
        "owner/owner_id: 'commercial:other:neurosphere:owner:x' is outside commercial:contoso"
    ]


def test_check_evaluation_times() -> None:
    result = ex("evaluation/v1/examples/valid/evaluation-result.offline-llm-judge.json")
    assert v.check_evaluation_times(result) == []
    bad = copy.deepcopy(result)
    bad["started_at"], bad["completed_at"] = bad["completed_at"], bad["started_at"]
    assert v.check_evaluation_times(bad)
    bad = copy.deepcopy(result)
    bad["sampling"]["window"]["end"] = bad["sampling"]["window"]["start"]
    assert v.check_evaluation_times(bad)


def test_check_evaluation_score_scale() -> None:
    result = ex("evaluation/v1/examples/valid/evaluation-result.offline-llm-judge.json")
    assert v.check_evaluation_score_scale(result) == []
    score = next(s for s in result["scores"] if s["value"] is not None)
    score["value"] = score["scale"]["max"] + 1
    assert v.check_evaluation_score_scale(result)


def test_check_evaluation_sampling_counts() -> None:
    result = ex(
        "evaluation/v1/examples/valid/evaluation-result.online-programmatic-government.json"
    )
    assert v.check_evaluation_sampling_counts(result) == []
    result["sampling"]["population_size"] = 10
    result["sampling"]["sample_size"] = 11
    assert v.check_evaluation_sampling_counts(result)
    result["sampling"]["population_size"] = None
    assert v.check_evaluation_sampling_counts(result) == []
