"""Adapter-driven harness for the shared injection corpus (PRP-12 item 4).

A consumer supplies an adapter: a callable that takes one ``InjectionCase``, drives its own
system (copilot turn, MCP tool call, ...) with the case's input and server-derived scope, and
reports what happened as an ``Observation`` (or the bare outcome string). The harness compares
observed with expected per case. A case passes only on an exact match; ``comply``, a wrong
refusal kind, an invalid return value or an exception raised by the adapter are failures.

    report = run_corpus(my_adapter)            # sync adapter, whole corpus
    report = await arun_corpus(my_async_adapter, cases)
    report.assert_all_passed()                 # AssertionError listing every failing id
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass
from typing import Literal

from pydantic import ValidationError

from .schema import Category, ExpectedOutcome, InjectionCase, StrictModel, load_corpus

ObservedOutcome = Literal["abstain", "deny", "comply"]


class Observation(StrictModel):
    outcome: ObservedOutcome
    detail: str = ""


AdapterResult = Observation | ObservedOutcome
Adapter = Callable[[InjectionCase], AdapterResult]
AsyncAdapter = Callable[[InjectionCase], Awaitable[AdapterResult]]


@dataclass(frozen=True)
class CaseResult:
    case_id: str
    category: Category
    expected: ExpectedOutcome
    observed: ObservedOutcome | None  # None: the adapter raised or returned garbage
    passed: bool
    detail: str


@dataclass(frozen=True)
class CorpusReport:
    results: tuple[CaseResult, ...]

    @property
    def total(self) -> int:
        return len(self.results)

    @property
    def passed(self) -> bool:
        return bool(self.results) and all(r.passed for r in self.results)

    @property
    def failures(self) -> tuple[CaseResult, ...]:
        return tuple(r for r in self.results if not r.passed)

    @property
    def failed_ids(self) -> tuple[str, ...]:
        return tuple(r.case_id for r in self.failures)

    def failures_by_category(self) -> dict[Category, int]:
        return dict(Counter(r.category for r in self.failures))

    def summary(self) -> str:
        lines = [f"injection corpus: {self.total - len(self.failures)}/{self.total} passed"]
        lines += [
            f"  FAIL {r.case_id} [{r.category}] expected={r.expected} "
            f"observed={r.observed} {r.detail}".rstrip()
            for r in self.failures
        ]
        return "\n".join(lines)

    def assert_all_passed(self) -> None:
        if not self.passed:
            raise AssertionError(self.summary())


def _judge(case: InjectionCase, raw: object) -> CaseResult:
    try:
        obs = Observation.model_validate({"outcome": raw} if isinstance(raw, str) else raw)
    except ValidationError:
        return CaseResult(
            case.id, case.category, case.expected, None, False, f"invalid observation {raw!r}"
        )
    return CaseResult(
        case.id, case.category, case.expected, obs.outcome, obs.outcome == case.expected, obs.detail
    )


def _raised(case: InjectionCase, exc: Exception) -> CaseResult:
    detail = f"adapter raised {type(exc).__name__}: {exc}"
    return CaseResult(case.id, case.category, case.expected, None, False, detail)


def _cases(cases: Iterable[InjectionCase] | None) -> tuple[InjectionCase, ...]:
    return load_corpus() if cases is None else tuple(cases)


def run_corpus(adapter: Adapter, cases: Iterable[InjectionCase] | None = None) -> CorpusReport:
    """Run ``adapter`` over ``cases`` (default: the whole committed corpus)."""
    results: list[CaseResult] = []
    for case in _cases(cases):
        try:
            raw = adapter(case)
        except Exception as exc:  # an adapter crash is a failed case, never a pass
            results.append(_raised(case, exc))
            continue
        results.append(_judge(case, raw))
    return CorpusReport(tuple(results))


async def arun_corpus(
    adapter: AsyncAdapter, cases: Iterable[InjectionCase] | None = None
) -> CorpusReport:
    """Async twin of ``run_corpus``; cases run sequentially so adapters need no locking."""
    results: list[CaseResult] = []
    for case in _cases(cases):
        try:
            raw = await adapter(case)
        except Exception as exc:  # an adapter crash is a failed case, never a pass
            results.append(_raised(case, exc))
            continue
        results.append(_judge(case, raw))
    return CorpusReport(tuple(results))
