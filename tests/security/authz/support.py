"""Assertion helpers shared by the negative-suite test modules."""

from collections import Counter
from typing import Any

from neurosphere_core.audit import is_allow_record

from .world import (
    CUSTOMERS,
    DOMAINS,
    PLATFORM_CHAIN,
    Deployment,
    Who,
    World,
    chain_for,
    principal_id_for,
    run,
)


class AuditProbe:
    """Snapshot of one customer's audit chains; ``new`` returns records appended since."""

    def __init__(self, dep: Deployment) -> None:
        self.dep = dep
        self._marks = run(self._snapshot())

    def _chains(self) -> list[str]:
        return [chain_for(self.dep.customer, d) for d in (*DOMAINS, PLATFORM_CHAIN)]

    async def _snapshot(self) -> dict[str, int]:
        marks: dict[str, int] = {}
        for chain in self._chains():
            tail = await self.dep.audit_repo.tail(chain)
            marks[chain] = 0 if tail is None else tail.sequence + 1
        return marks

    async def _new(self) -> list[Any]:
        out: list[Any] = []
        for chain, start in self._marks.items():
            out.extend(await self.dep.audit_repo.read_range(chain, start=start, limit=500))
        return out

    def new(self) -> list[Any]:
        return run(self._new())

    def assert_decision(
        self,
        expected: str,
        *,
        who: Who | None = None,
        reason: str | None = None,
        code: str = "forbidden",
    ) -> None:
        records = self.new()
        if expected == "none":
            assert records == [], "a case marked as an audit gap unexpectedly produced a record"
            return
        assert len(records) == 1, f"expected exactly one audit record, got {len(records)}"
        record = records[0]
        if expected == "allow":
            outcome_detail = record.outcome.detail if record.outcome else None
            assert is_allow_record(record.kind, outcome_detail), "expected an allow record"
        else:
            assert record.kind == "denied", f"expected a denied record, got {record.kind}"
            assert record.denial is not None
            assert record.denial.code == code
            if reason is not None:
                assert record.denial.reason == reason
        if who is not None:
            assert record.actor.principal_pseudonym == principal_id_for(who).rsplit(":", 1)[-1]


def decision_of(record: Any) -> tuple[str, str | None]:
    if record.kind == "denied":
        return ("denied", record.denial.reason)
    detail = record.outcome.detail if record.outcome else None
    return ("allow", None) if is_allow_record(record.kind, detail) else (record.kind, None)


class Ledger:
    """Expected audit decisions for a multi-step scenario, verified against the stores."""

    def __init__(self, world: World) -> None:
        self._probes = {c: AuditProbe(world[c]) for c in CUSTOMERS}
        self._want: dict[str, Counter[tuple[str, str | None]]] = {c: Counter() for c in CUSTOMERS}

    def note(self, dep: Deployment, decision: str, reason: str | None = None) -> None:
        self._want[dep.customer][(decision, reason)] += 1

    def verify(self) -> None:
        for customer, probe in self._probes.items():
            got = Counter(decision_of(r) for r in probe.new())
            assert got == self._want[customer], (
                f"{customer}: audit {dict(got)} != {dict(self._want[customer])}"
            )
