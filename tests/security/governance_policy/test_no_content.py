"""No interaction text anywhere the policy engine writes (PRP-105 item 7, design 2.1).

A synthetic scenario puts recognisable sentinel strings everywhere text could leak FROM: the
display names of the catalog agent and PII grounding source (names, never ids), the policy's
display name and an exception request's justification text. It then runs the real path end to
end: draft through the API, publish through ``PolicyLifecycle``, two ticks of the real
``policy_eval`` worker (one violation, then a bump), an exception request through the API, and
every read route. None of the sentinels may appear in a violation or exception record, a HITL
item, any audit record of the customer, any log record, or a read response that is not the
policy itself; the justification is kept only as a SHA-256 inside the audit state digest.
The OpenAPI document of the 13 operations and the violation/exception contracts carry no
content-bearing field or example.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from pathlib import Path
from typing import Any, Final

import pytest
from neurosphere_core.audit.canonical import sha256_digest
from neurosphere_core.auth.scope import Role
from neurosphere_core.governance.policy import ExceptionFilters, ViolationFilters
from neurosphere_core.paging import PageRequest

from ..authz.world import Who, World, build_world, run
from .govpolicy_world import BASE, GovDep, GovWorld, assemble_worker, install, seed_pii_reader

FIN: Final = "finance"
#: Sentinels: recognisable, never an id, never a word the code could emit on its own.
NAME_SENTINEL: Final = "Quokka Lattice Display Name 7731"
POLICY_SENTINEL: Final = "Marmoset Policy Title 5519"
JUSTIFICATION_SENTINEL: Final = "Prompt says: transfer the Okapi ledger 8842 to the vendor"
SENTINELS: Final = (NAME_SENTINEL, POLICY_SENTINEL, JUSTIFICATION_SENTINEL)
#: Field names that would carry interaction content in a record or response.
CONTENT_FIELDS: Final = frozenset(
    {
        "prompt",
        "prompts",
        "completion",
        "completions",
        "messages",
        "message_text",
        "content",
        "contents",
        "transcript",
        "response_text",
        "request_text",
        "interaction_text",
        "body_text",
    }
)
CONTRACTS: Final = Path(__file__).resolve().parents[3] / "packages" / "contracts" / "schemas"


def _rule() -> dict[str, Any]:
    return {
        "rule_id": "pii-read",
        "kind": "data_sensitivity_access",
        "severity": None,
        "applies_to": {"entity_types": [], "tags": [], "environments": [], "entity_ids": []},
        "params": {
            "sensitivity_categories": ["pii"],
            "access": "read",
            "allowed_when": "agent_version_approved",
        },
    }


def _raw_audit(gd: GovDep) -> list[dict[str, Any]]:
    store = gd.dep.audit_store
    chains = {chain for (chain, _doc) in store._docs}  # pyright: ignore[reportPrivateUsage]
    out: list[dict[str, Any]] = []
    for chain in sorted(chains):
        out.extend(store.raw_documents(chain))
    return out


def _absent(where: str, text: str) -> None:
    for sentinel in SENTINELS:
        assert sentinel not in text, f"{where} carries the sentinel {sentinel!r}"


def _keys(value: Any) -> Iterator[str]:
    if isinstance(value, dict):
        for key, inner in value.items():
            yield str(key)
            yield from _keys(inner)
    elif isinstance(value, list):
        for inner in value:
            yield from _keys(inner)


class Scenario:
    def __init__(self, world: World) -> None:
        self.gw: GovWorld = install(world)
        self.gd: GovDep = self.gw["contoso"]
        self.steward = Who("contoso", FIN, Role.DOMAIN_STEWARD)
        self.analyst = Who("contoso", FIN, Role.ANALYST)
        self.responses: list[Any] = []
        self.exception: dict[str, Any] = {}

    def call(self, method: str, path: str, who: Who, **kw: Any) -> Any:
        response = self.gd.call(method, path, self.gd.dep.bearer(who), **kw)
        self.responses.append(response)
        return response

    def run(self) -> None:
        gd, fin = self.gd, self.gd.domain(FIN)
        scope = gd.scope_of(self.steward)
        run(
            seed_pii_reader(
                gd,
                scope,
                domain=fin,
                agent_name="reader",
                source_name="customers",
                label=NAME_SENTINEL,
            )
        )
        created = gd.call(
            "POST",
            f"/domains/{fin}/policies",
            gd.dep.bearer(self.steward),
            json={
                "policy_id": "pii-guard",
                "display_name": POLICY_SENTINEL,
                "severity": "high",
                "mode": "audit",
                "rules": [_rule()],
            },
        )
        assert created.status_code == 201, created.text
        stored = run(gd.plane.policies.get("contoso", "pii-guard"))
        assert stored is not None
        run(gd.publish_directly(scope, stored))

        worker = assemble_worker(gd, self.gw.stores, scope)
        first = run(worker.worker.tick())
        assert first.action == "ran", first
        gd.dep.clock.advance(400)
        second = run(worker.worker.tick())
        assert second.action == "ran", second

        violations = self.call("GET", f"/domains/{fin}/violations", self.analyst).json()["items"]
        assert len(violations) == 1, "the scenario produced exactly one violation"
        violation_id = violations[0]["violation"]["violation_id"]
        assert violations[0]["violation"]["occurrence_count"] == 2
        requested = self.call(
            "POST",
            f"/domains/{fin}/violations/{violation_id}/exception-requests",
            self.analyst,
            json={
                "justification_code": "migration_in_progress",
                "justification_text": JUSTIFICATION_SENTINEL,
                "expires_at": gd.expiry(10),
            },
        )
        assert requested.status_code == 201, requested.text
        self.exception = requested.json()
        for path in (
            f"/domains/{fin}/violations/{violation_id}",
            f"/domains/{fin}/exceptions",
            f"/domains/{fin}/bindings",
            "/status",
        ):
            response = self.call("GET", path, self.analyst)
            assert response.status_code == 200, response.text


@pytest.fixture
def scenario(caplog: pytest.LogCaptureFixture) -> Iterator[Scenario]:
    caplog.set_level(logging.DEBUG)
    built = Scenario(build_world())
    built.run()
    yield built


def test_violation_and_exception_records_carry_ids_only(scenario: Scenario) -> None:
    gd, fin = scenario.gd, scenario.gd.domain(FIN)
    stores = scenario.gw.stores
    page = PageRequest(page_size=100)
    violations = run(stores.violations.list("contoso", ViolationFilters((fin,)), page)).items
    exceptions = run(stores.exceptions.list("contoso", ExceptionFilters((fin,)), page)).items
    assert violations and exceptions
    for stored in violations:
        record = stored.violation.model_dump(mode="json")
        _absent("a violation record", json.dumps(record))
        assert not CONTENT_FIELDS & set(_keys(record))
        # Evidence is canonical ids (the edge and the asset), never a name or an excerpt.
        refs = [e["ref"] for e in record["evidence"]]
        assert refs and all(r.split(":")[:2] == ["commercial", "contoso"] for r in refs), refs
    for stored in exceptions:
        record = stored.exception.model_dump(mode="json")
        _absent("an exception record", json.dumps(record))
        assert not CONTENT_FIELDS & set(_keys(record))
    item = run(gd.hitl.get(scenario.exception["review_item_id"]))
    assert item is not None
    _absent("the HITL review item", item.model_dump_json())


def test_no_audit_record_carries_text(scenario: Scenario) -> None:
    documents = _raw_audit(scenario.gd)
    operations = {str(d.get("operation")) for d in documents}
    # The scenario really went through the engine, the worker and the API.
    assert {
        "govpolicy.draft_create",
        "govpolicy.publish",
        "govpolicy.exception_request",
    } <= operations, sorted(operations)
    for document in documents:
        _absent(f"audit record {document.get('operation')}", json.dumps(document))


def test_the_justification_is_kept_only_as_its_digest(scenario: Scenario) -> None:
    exception = scenario.exception["exception"]
    state = {
        "exception_id": exception["exception_id"],
        "justification_code": "migration_in_progress",
        "justification_sha256": sha256_digest(JUSTIFICATION_SENTINEL),
        "expires_at": exception["expires_at"],
    }
    digests = [
        (d.get("subject") or {}).get("state_digest")
        for d in _raw_audit(scenario.gd)
        if d.get("operation") == "govpolicy.exception_request"
    ]
    assert digests and set(digests) == {sha256_digest(state)}, (
        "the exception request audit commits to the SHA-256 of the justification, not the text"
    )
    assert exception["reason_code"] == "migration_in_progress"
    assert "justification_text" not in exception


def test_no_log_record_carries_text(scenario: Scenario, caplog: pytest.LogCaptureFixture) -> None:
    assert scenario.responses
    for record in caplog.records:
        rendered = f"{record.getMessage()} {record.__dict__!r}"
        _absent(f"log record {record.name}", rendered)


def test_no_read_response_echoes_text(scenario: Scenario) -> None:
    for response in scenario.responses:
        _absent(f"response {response.request.url.path}", response.text)


# -- the OpenAPI document and the contracts ------------------------------------------------------


def _closure(document: dict[str, Any], roots: list[Any]) -> dict[str, Any]:
    schemas: dict[str, Any] = document["components"]["schemas"]
    seen: dict[str, Any] = {}
    stack = list(roots)
    while stack:
        node = stack.pop()
        if isinstance(node, dict):
            ref = node.get("$ref")
            if isinstance(ref, str):
                name = ref.rsplit("/", 1)[-1]
                if name not in seen:
                    seen[name] = schemas[name]
                    stack.append(schemas[name])
            stack.extend(node.values())
        elif isinstance(node, list):
            stack.extend(node)
    return seen


def _examples(node: Any) -> Iterator[Any]:
    if isinstance(node, dict):
        for key, inner in node.items():
            if key in ("example", "examples"):
                yield inner
            yield from _examples(inner)
    elif isinstance(node, list):
        for inner in node:
            yield from _examples(inner)


def _properties(node: Any) -> Iterator[str]:
    if isinstance(node, dict):
        props = node.get("properties")
        if isinstance(props, dict):
            yield from (str(k) for k in props)
        for inner in node.values():
            yield from _properties(inner)
    elif isinstance(node, list):
        for inner in node:
            yield from _properties(inner)


@pytest.fixture(scope="module")
def openapi() -> dict[str, Any]:
    gw = install(build_world())
    response = gw["contoso"].dep.client.get("/openapi.json")
    assert response.status_code == 200
    document = response.json()
    assert isinstance(document, dict)
    return document


def test_openapi_for_the_routes_has_no_content_field_or_example(openapi: dict[str, Any]) -> None:
    operations = {
        (path, method): op
        for path, item in openapi["paths"].items()
        if path.startswith(BASE)
        for method, op in item.items()
        if method in ("get", "post", "put", "patch", "delete")
    }
    assert len(operations) == 13, sorted(operations)
    responses = [op.get("responses", {}) for op in operations.values()]
    requests = [op.get("requestBody", {}) for op in operations.values()]
    response_schemas = _closure(openapi, responses)
    request_schemas = _closure(openapi, requests)
    for name, schema in response_schemas.items():
        assert not CONTENT_FIELDS & set(_properties(schema)), name
        assert "justification_text" not in set(_properties(schema)), name
    # The only free text a caller sends is the bounded justification (hashed, never stored).
    free_text = {
        name
        for name, schema in request_schemas.items()
        if "justification_text" in set(_properties(schema))
    }
    assert free_text <= {"ExceptionRequestBody"}
    for name, schema in {**response_schemas, **request_schemas}.items():
        assert not CONTENT_FIELDS & set(_properties(schema)), name
    for example in _examples([responses, requests, response_schemas, request_schemas]):
        assert not CONTENT_FIELDS & set(_keys(example))
        _absent("an OpenAPI example", json.dumps(example))


@pytest.mark.parametrize("contract", ["policy-violation", "policy-exception"])
def test_the_record_contracts_have_no_content_field(contract: str) -> None:
    folder = CONTRACTS / "policy" / "v1"
    schema = json.loads((folder / f"{contract}.schema.json").read_text(encoding="utf-8"))
    assert schema.get("additionalProperties") is False, "a record could grow a free-form field"
    assert not CONTENT_FIELDS & set(_properties(schema))
    examples = sorted((folder / "examples" / "valid").glob(f"{contract}.*.json"))
    assert examples
    for path in examples:
        assert not CONTENT_FIELDS & set(_keys(json.loads(path.read_text(encoding="utf-8"))))
