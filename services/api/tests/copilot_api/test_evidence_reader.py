"""The production evidence reader (PRP-19 round 2 item 9): real in-memory stores, real engine."""

from __future__ import annotations

import json
from pathlib import Path

from copilot_api_harness import (  # pyright: ignore[reportMissingImports]
    FINANCE,
    NOW,
    OPERATIONS,
    SCHEMAS,
    RecordingEvidence,
    ScriptedAdapter,
    agent,
    call,
    make_scope,
    recommendation,
    run_turn,
    say,
)
from neurosphere_api.copilot import CopilotEngine, CopilotSettings, ToolPorts
from neurosphere_api.copilot.evidence import MAX_EVIDENCE_IDS, StoreEvidenceReader
from neurosphere_api.copilot.models import CitationEvent
from neurosphere_contracts.evaluation.v1.evaluation_result import EvaluationResult
from neurosphere_core.aggregates import InMemoryAggregateStore
from neurosphere_core.catalog.repo import InMemoryCatalogRepository
from neurosphere_core.evaluation.store import InMemoryEvaluationStore
from neurosphere_core.recommendations import InMemoryRecommendationStore
from neurosphere_core.scope import IdentityScope

FIN_REC = "commercial:contoso:neurosphere:recommendation:rec-0001"
OPS_REC = "commercial:contoso:neurosphere:recommendation:rec-0002"
FIN_AGENT = "commercial:contoso:foundry:agent:fin-1"
OPS_AGENT = "commercial:contoso:foundry:agent:ops-1"
EVAL_ID = "eval:offline-42"


class EvaluationStoreWithPointRead(InMemoryEvaluationStore):
    """The shipped store has no by-id read; the reader uses ``get_result`` when one exists."""

    async def get_result(
        self, scope: IdentityScope, domain: str, evaluation_id: str
    ) -> EvaluationResult | None:
        for result in await self.results(scope, domain):
            if result.evaluation_id.root == evaluation_id:
                return result
        return None


def _auditor() -> IdentityScope:
    return make_scope([("analyst", [FINANCE]), ("security_auditor", [FINANCE])], [FINANCE])


def _evaluation() -> EvaluationResult:
    path = Path(SCHEMAS) / "evaluation/v1/examples/valid/evaluation-result.offline-llm-judge.json"
    return EvaluationResult.model_validate(json.loads(path.read_text(encoding="utf-8")))


class _Catalog(InMemoryCatalogRepository):
    """Serves fixed entities, filtered to the scope as the real repository does."""

    def __init__(self) -> None:
        super().__init__()
        self._entities = {
            e.id: e for e in (agent(FIN_AGENT, FINANCE), agent(OPS_AGENT, OPERATIONS))
        }

    async def get_entity(self, scope: IdentityScope, entity_id: str):  # type: ignore[override]
        entity = self._entities.get(entity_id)
        if entity is None or entity.domain_id.root not in scope.allowed_domains:
            return None
        return entity


def _reader() -> StoreEvidenceReader:
    return StoreEvidenceReader(
        recommendations=InMemoryRecommendationStore(
            [recommendation(1, FINANCE), recommendation(2, OPERATIONS)]
        ),
        evaluations=EvaluationStoreWithPointRead([_evaluation()]),
        catalog=_Catalog(),
    )


async def test_each_supported_kind_resolves_with_a_pointer_and_real_timestamp() -> None:
    found = await _reader().get_many(_auditor(), [FINANCE], [FIN_REC, EVAL_ID, FIN_AGENT])
    by_id = {r.evidence_id: r for r in found}
    assert set(by_id) == {FIN_REC, EVAL_ID, FIN_AGENT}
    assert by_id[FIN_REC].kind == "recommendation"
    assert by_id[FIN_REC].ref == f"recommendation:{FIN_REC}"
    assert by_id[EVAL_ID].kind == "evaluation_result"
    assert by_id[EVAL_ID].observed_at == "2026-10-10T01:42:00Z"
    assert by_id[FIN_AGENT].kind == "catalog_entity"
    assert by_id[FIN_AGENT].observed_at == "2026-10-21T08:00:00Z"
    assert all(r.observed_at is not None and r.domain_id == FINANCE for r in found)


async def test_cross_domain_and_unknown_ids_are_omitted() -> None:
    found = await _reader().get_many(
        _auditor(),
        [FINANCE],
        [OPS_REC, OPS_AGENT, "commercial:contoso:neurosphere:recommendation:nope", "nope", FIN_REC],
    )
    assert [r.evidence_id for r in found] == [FIN_REC]


async def test_server_domains_outside_the_scope_are_ignored() -> None:
    found = await _reader().get_many(_auditor(), [OPERATIONS], [OPS_REC, OPS_AGENT])
    assert found == ()


async def test_absent_stores_omit_their_kind_and_never_raise() -> None:
    found = await StoreEvidenceReader().get_many(_auditor(), [FINANCE], [FIN_REC, EVAL_ID, "x"])
    assert found == ()
    # The shipped evaluation store has no by-id read: that kind is omitted, not scanned.
    plain = StoreEvidenceReader(evaluations=InMemoryEvaluationStore([_evaluation()]))
    assert await plain.get_many(_auditor(), [FINANCE], [EVAL_ID]) == ()


async def test_input_is_bounded() -> None:
    ids = [FIN_REC] + [f"commercial:contoso:neurosphere:recommendation:x{i}" for i in range(80)]
    ids.append(FIN_AGENT)  # beyond the cap
    found = await _reader().get_many(_auditor(), [FINANCE], ids)
    assert [r.evidence_id for r in found] == [FIN_REC]
    assert len(ids) > MAX_EVIDENCE_IDS


async def test_the_engine_answers_an_evidence_question_with_a_fresh_citation() -> None:
    model = ScriptedAdapter(
        call(
            "get_evidence",
            {
                "evidence_ids": [FIN_REC],
                "budget": {"timeout_ms": 1000, "limit": 10, "max_depth": 0},
            },
        ),
        say("The recommendation supports this [cite:r1]."),
    )
    engine = CopilotEngine(
        adapter=model,
        ports=ToolPorts(
            catalog=_Catalog(),
            metrics=InMemoryAggregateStore(),
            recommendations=InMemoryRecommendationStore([recommendation(1, FINANCE)]),
            evidence=_reader(),
        ),
        settings=CopilotSettings(),
        clock=lambda: NOW,
    )
    turn = await run_turn(engine, _auditor())
    assert turn.terminal.name == "done"
    [citation] = [e.payload for e in turn.of("citation")]
    assert isinstance(citation, CitationEvent)
    assert citation.record_id == FIN_REC
    assert citation.as_of is not None and citation.freshness != "unknown"


async def test_the_unwired_default_still_abstains() -> None:
    # Control: the same question through a recording fake with no records abstains.
    model = ScriptedAdapter(
        call(
            "get_evidence",
            {
                "evidence_ids": [FIN_REC],
                "budget": {"timeout_ms": 1000, "limit": 10, "max_depth": 0},
            },
        ),
        say("Supported [cite:r1]."),
    )
    engine = CopilotEngine(
        adapter=model,
        ports=ToolPorts(
            catalog=_Catalog(),
            metrics=InMemoryAggregateStore(),
            recommendations=InMemoryRecommendationStore(),
            evidence=RecordingEvidence(),
        ),
        settings=CopilotSettings(),
        clock=lambda: NOW,
    )
    turn = await run_turn(engine, _auditor())
    assert turn.terminal.name == "abstain"
