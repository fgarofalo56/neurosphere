"""``content_rule``: captured interactions with listed detected categories (PRP-105 item 2).

Counts only, through the :class:`InteractionFindingReader` port: per subject, the matches of the
rule's ``detected_categories`` in its ``parts`` over the last ``window_minutes``. A subject at or
above ``min_count`` breaks the rule. Evidence: interaction record ids; categories: the detected
category names; counts: per category. No interaction body is ever read. With no reader bound
the kind is unavailable (the builtin registration does not register it).
"""

from __future__ import annotations

from collections import defaultdict
from datetime import timedelta
from typing import Final

from neurosphere_contracts.policy.v1.policy_definition import (
    ContentRuleParams,
    PolicyDefinition,
    PolicyRule,
)

from neurosphere_core.governance.policy.rules.base import (
    MAX_FINDING_EVIDENCE,
    FindingEvidence,
    RuleContext,
    RuleOutcome,
    params_as,
    strings_of,
)
from neurosphere_core.governance.policy.rules.findings_port import (
    InteractionFindingCount,
    InteractionFindingReader,
)
from neurosphere_core.governance.policy.rules.scan import AppliesTo, FindingCollector

__all__ = ["KIND", "ContentRuleEvaluator"]

KIND: Final = "content_rule"


class ContentRuleEvaluator:
    """Evaluator of ``content_rule`` over detection-finding counts."""

    def __init__(self, reader: InteractionFindingReader) -> None:
        self._reader = reader

    @property
    def kind(self) -> str:
        return KIND

    async def evaluate(
        self, ctx: RuleContext, policy: PolicyDefinition, rule: PolicyRule
    ) -> RuleOutcome:
        params = params_as(rule, ContentRuleParams, KIND)
        out = FindingCollector(KIND)
        if not ctx.domain_ids or ctx.budget.expired():
            return out.outcome(ctx)
        limit = ctx.budget.remaining_subjects
        page = await self._reader.count_findings(
            ctx.scope,
            domain_ids=list(ctx.domain_ids),
            categories=strings_of(params.detected_categories),
            parts=strings_of(params.parts),
            start=ctx.now - timedelta(minutes=params.window_minutes or 60),
            end=ctx.now,
            limit=limit,
        )
        wanted = set(strings_of(params.detected_categories))
        by_subject: dict[str, list[InteractionFindingCount]] = defaultdict(list)
        for row in page.counts:
            if row.category in wanted:
                by_subject[row.subject_id].append(row)
        applies = AppliesTo.of(rule)
        min_count = params.min_count or 1
        for subject_id in sorted(by_subject):
            if not ctx.budget.take():
                break
            rows = by_subject[subject_id]
            first = rows[0]
            if not applies.matches_unregistered(subject_id, first.subject_type):
                continue
            total = sum(r.count for r in rows)
            if total < min_count:
                continue
            refs = sorted({i for r in rows for i in r.interaction_ids})[:MAX_FINDING_EVIDENCE]
            if not refs:
                refs = [subject_id]
            out.add(
                subject_id=subject_id,
                subject_type=first.subject_type,
                domain_id=first.domain_id,
                evidence_class="detected_content",
                evidence=tuple(
                    FindingEvidence(
                        kind="interaction_record" if ref != subject_id else "catalog_entity",
                        ref=ref,
                    )
                    for ref in refs
                ),
                counts=_per_category(rows),
                categories=sorted({r.category for r in rows}),
            )
        if page.truncated:
            ctx.budget.mark("subject_budget")
        return out.outcome(ctx)


def _per_category(rows: list[InteractionFindingCount]) -> dict[str, int]:
    totals: dict[str, int] = {}
    for row in rows:
        totals[row.category] = totals.get(row.category, 0) + row.count
    return totals
