"""Budgets are enforced before each call: reserve worst case, stop, report, never overshoot."""

from __future__ import annotations

from decimal import Decimal

from neurosphere_core.evaluation.judge import JudgeRequest
from neurosphere_workers.evaluation.budget import (
    BudgetDenial,
    BudgetLedger,
    BudgetLimits,
    Reservation,
    estimate_input_tokens,
    price_call,
)
from neurosphere_workers.evaluation.source import InMemoryRecordSource

from .support import (
    CountingJudge,
    calibrated_report,
    ledger,
    llm_config,
    make_service,
    online_config,
    population,
    record,
)

IN, OUT = 100, 20  # tokens the judge double reports per call


def _worst_case(cfg_max_output: int = 256) -> int:
    request = JudgeRequest(
        judge_config_id="judge-a",
        judge_config_version="1",
        rubric_id="rubric-online",
        rubric_version="1",
        dimension="task_success",
        item_id="0" * 64,
        classification="public",
        payload={
            "span_kind": "agent_run",
            "outcome": "success",
            "duration_ms": 99,
            "retry_attempt": None,
        },
    )
    return estimate_input_tokens(request) + cfg_max_output


# --- ledger ---------------------------------------------------------------------------------


def test_ledger_reserves_settles_and_releases() -> None:
    led = BudgetLedger(
        run_limits=BudgetLimits(tokens=1000, cost=Decimal("1")),
        domain_limits=BudgetLimits(tokens=600, cost=Decimal("1")),
    )
    first = led.reserve("d", 500, Decimal("0.1"))
    assert isinstance(first, Reservation)
    denied = led.reserve("d", 200, Decimal("0.1"))  # 500 reserved + 200 > 600 domain tokens
    assert isinstance(denied, BudgetDenial)
    assert denied.code == "domain_tokens"
    led.settle(first, 120, Decimal("0.01"))  # unused part is released
    assert led.run_consumed == (120, Decimal("0.01"))
    second = led.reserve("d", 480, Decimal("0.1"))  # 120 + 480 == 600 fits exactly
    assert isinstance(second, Reservation)
    led.release(second)
    assert led.domain_consumed("d") == (120, Decimal("0.01"))
    assert led.open_reservations == 0


def test_ledger_denial_codes_cover_run_and_cost() -> None:
    led = BudgetLedger(
        run_limits=BudgetLimits(tokens=100, cost=Decimal("0.5")),
        domain_limits=BudgetLimits(tokens=1000, cost=Decimal("5")),
    )
    over_tokens = led.reserve("d", 101, Decimal("0"))
    assert isinstance(over_tokens, BudgetDenial) and over_tokens.code == "run_tokens"
    over_cost = led.reserve("d", 10, Decimal("0.51"))
    assert isinstance(over_cost, BudgetDenial) and over_cost.code == "run_cost"
    assert led.run_consumed == (0, Decimal(0))


def test_overrun_is_recorded_not_hidden() -> None:
    led = BudgetLedger(
        run_limits=BudgetLimits(tokens=100, cost=Decimal("1")),
        domain_limits=BudgetLimits(tokens=100, cost=Decimal("1")),
    )
    res = led.reserve("d", 50, Decimal("0.1"))
    assert isinstance(res, Reservation)
    led.settle(res, 150, Decimal("0.1"))
    assert led.overruns == 1


def test_price_call_is_decimal_and_exact() -> None:
    cost = price_call(llm_config(), 1000, 500)  # 1k*0.002 + 0.5k*0.008
    assert cost == Decimal("0.006")


# --- service --------------------------------------------------------------------------------


async def test_run_stops_mid_sample_and_reports_budget_exhausted_with_coverage() -> None:
    worst = _worst_case()
    limit = 3 * (IN + OUT) + worst + 50  # room for 4 calls: the 5th worst case cannot fit
    led = ledger(run=BudgetLimits(tokens=limit, cost=Decimal("100")))
    cfg = llm_config()
    judge = CountingJudge(input_tokens=IN, output_tokens=OUT)
    service = make_service(judge, [cfg], budget=led)
    records = [record(n, classification="public") for n in range(12)]
    report = await service.run_online(InMemoryRecordSource(records), online_config(cfg))

    assert report.status == "budget_exhausted"
    assert report.budget_exhausted_reason is not None
    assert report.budget_exhausted_reason.startswith("run_tokens")
    assert judge.call_count == 4
    assert report.evaluated_total == 4
    assert report.unevaluated_total == 12 - 4
    assert report.sampled_total == 12
    assert report.skip_counts == {"budget_exhausted": 8}
    # Coverage achieved is reported, not silently truncated.
    assert sum(c.evaluated for c in report.coverage) == 4
    assert sum(c.sampled for c in report.coverage) == 12
    # Invariants: consumed never exceeds the budget; the refused call's worst case would have.
    consumed, _cost = led.run_consumed
    assert consumed == 4 * (IN + OUT)
    assert consumed <= limit
    assert consumed + worst > limit
    assert led.overruns == 0
    assert led.open_reservations == 0


async def test_cost_budget_stops_the_run_too() -> None:
    cfg = llm_config()
    worst_cost = price_call(cfg, _worst_case() - 256, 256)
    led = ledger(run=BudgetLimits(tokens=10_000_000, cost=worst_cost * 2))
    judge = CountingJudge(input_tokens=IN, output_tokens=OUT)
    service = make_service(judge, [cfg], budget=led)
    records = [record(n, classification="public") for n in range(60)]
    report = await service.run_online(InMemoryRecordSource(records), online_config(cfg))
    assert report.status == "budget_exhausted"
    assert report.budget_exhausted_reason is not None
    assert report.budget_exhausted_reason.startswith("run_cost")
    assert 0 < judge.call_count < 60
    assert led.run_consumed[1] <= worst_cost * 2


async def test_zero_budget_makes_no_call_at_all() -> None:
    led = ledger(run=BudgetLimits(tokens=0, cost=Decimal(0)))
    cfg = llm_config()
    judge = CountingJudge()
    service = make_service(judge, [cfg], budget=led)
    report = await service.run_online(
        InMemoryRecordSource([record(1, classification="public")]), online_config(cfg)
    )
    assert judge.call_count == 0
    assert report.status == "budget_exhausted"
    assert report.evaluated_total == 0


async def test_domain_budget_is_enforced_across_two_runs() -> None:
    worst = _worst_case()
    # Domain allows 3 calls' actual usage plus one worst case in total; the run budget is huge.
    domain_limit = 3 * (IN + OUT) + worst + 10
    led = ledger(domain=BudgetLimits(tokens=domain_limit, cost=Decimal("100")))
    cfg = llm_config()
    judge = CountingJudge(input_tokens=IN, output_tokens=OUT)
    service = make_service(judge, [cfg], budget=led)

    first = await service.run_online(
        InMemoryRecordSource([record(n, classification="public") for n in range(2)]),
        online_config(cfg, run_id="run-1"),
    )
    assert first.status == "completed"
    assert judge.call_count == 2

    second = await service.run_online(
        InMemoryRecordSource([record(n, classification="public") for n in range(10, 16)]),
        online_config(cfg, run_id="run-2"),
    )
    assert second.status == "budget_exhausted"
    assert second.budget_exhausted_reason is not None
    assert second.budget_exhausted_reason.startswith("domain_tokens:dom-a")
    # Domain carried over: 2 calls in run 1, then only 2 more fit in run 2.
    assert judge.call_count == 4
    consumed, _ = led.domain_consumed("dom-a")
    assert consumed == 4 * (IN + OUT)
    assert consumed <= domain_limit
    # Run counters restarted for the second run.
    assert led.run_consumed[0] == 2 * (IN + OUT)


async def test_per_domain_override_stops_the_run_before_that_domains_call() -> None:
    cfg = llm_config()
    led = ledger(**{"dom-b": BudgetLimits(tokens=0, cost=Decimal(0))})
    judge = CountingJudge()
    service = make_service(judge, [cfg], budget=led)
    records = population(
        domains=("dom-a", "dom-b"), agents=("agent-a",), classifications=("public",), per_stratum=3
    )
    report = await service.run_online(InMemoryRecordSource(records), online_config(cfg))
    assert report.status == "budget_exhausted"
    assert report.budget_exhausted_reason == "domain_tokens:dom-b"
    assert led.domain_consumed("dom-b") == (0, Decimal(0))
    dom_a_ids = {x["doc_id"] for x in records[:3]}
    assert judge.call_count >= 1
    assert all(r.item_id in dom_a_ids for r in judge.calls)


async def test_budget_exhausted_result_is_partial() -> None:
    worst = _worst_case()
    led = ledger(run=BudgetLimits(tokens=2 * (IN + OUT) + worst + 10, cost=Decimal("100")))
    cfg = llm_config()
    judge = CountingJudge(input_tokens=IN, output_tokens=OUT)
    service = make_service(judge, [cfg], budget=led)
    records = [record(n, classification="public") for n in range(8)]
    cals = [calibrated_report(cfg, "task_success")]
    report = await service.run_online(
        InMemoryRecordSource(records), online_config(cfg), calibrations=cals
    )
    assert report.status == "budget_exhausted"
    (result,) = report.results
    assert result.status == "partial"
    assert result.sampling.sample_size == judge.call_count == 3
    assert result.evaluator_usage is not None
    assert result.evaluator_usage.judge_input_tokens is not None
    assert result.evaluator_usage.judge_input_tokens.root.root == 3 * IN
    assert result.evaluator_usage.estimated_cost is not None
    assert result.evaluator_usage.estimated_cost.price_version.root == "p1"
