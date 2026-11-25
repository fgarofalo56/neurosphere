"""PRP-101 item 6: labelled synthetic corpus, measured quality and the GD-19 gate.

The gate (Clarification 6, GD-19): every credential category and Luhn-valid payment cards reach
recall 1.0 end to end through ``redact`` on the corpus. Every other detector is measured and
reported (``report_quality.py`` writes the runbook table) without a threshold. This test never
rewrites the runbook; it only checks that the published table exists for the current set.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from neurosphere_core.classification import DEFAULT_SET_VERSION, default_detector_set

from .corpus import (
    CHAINED_CONTEXT,
    CONTEXTS,
    DEFAULT_SEED,
    GATED_CATEGORIES,
    NEGATIVE_KINDS,
    POSITIVE_KINDS,
    TABLE_END,
    TABLE_HEADER,
    TABLE_START,
    QualityReport,
    Sample,
    build_corpus,
    measure,
)
from .synth import CREDENTIAL_GENERATORS

RUNBOOK = Path(__file__).resolve().parents[4] / "docs" / "runbooks" / "content-classification.md"
_CHAINED_FIX = (
    "PRP-101 item 2 fix lane (secret_detectors.py, PasswordAssignmentDetector): in "
    "'password: client_secret = <value>' the outer label takes the inner label as its value "
    "and the real value is left in the output"
)


@pytest.fixture(scope="module")
def corpus() -> list[Sample]:
    return build_corpus(DEFAULT_SEED)


@pytest.fixture(scope="module")
def report(corpus: list[Sample]) -> QualityReport:
    return measure(corpus, seed=DEFAULT_SEED)


# --- corpus properties -----------------------------------------------------------------------


def test_corpus_is_reproducible_from_its_seed() -> None:
    assert build_corpus(7, 300) == build_corpus(7, 300)
    assert build_corpus(7, 300) != build_corpus(8, 300)
    assert build_corpus(7, 300)[:100] == build_corpus(7, 100)


def test_corpus_covers_every_kind_context_and_category(corpus: list[Sample]) -> None:
    kinds = {s.kind for s in corpus}
    assert set(CREDENTIAL_GENERATORS) <= kinds
    assert set(POSITIVE_KINDS) | NEGATIVE_KINDS == kinds
    assert {s.context for s in corpus} == set(CONTEXTS) | {CHAINED_CONTEXT}
    for kind in kinds:
        seen = {s.context for s in corpus if s.kind == kind} - {CHAINED_CONTEXT}
        assert seen == set(CONTEXTS), kind
    categories = {span.category for s in corpus for span in s.spans}
    detector_kinds = {k for d in default_detector_set().all_detectors for k in d.kinds}
    assert categories == detector_kinds
    assert GATED_CATEGORIES <= categories


def test_labels_are_consistent(corpus: list[Sample]) -> None:
    for sample in corpus:
        previous_end = 0
        for span in sorted(sample.spans, key=lambda s: s.start):
            assert previous_end <= span.start < span.end <= len(sample.text)
            assert span.start <= span.secret[0] < span.secret[1] <= span.end
            previous_end = span.end
        if sample.negative and sample.context != "mixed_row":  # a mixed row adds positives
            assert {s.category for s in sample.spans} <= {"guid"}, sample.kind
        else:
            assert sample.spans, sample.kind


# --- measurement (report only, except the gate) ----------------------------------------------


def test_every_detector_is_measured(report: QualityReport) -> None:
    ids = [d.detector_id for d in default_detector_set().all_detectors]
    assert [row.detector_id for row in report.detectors] == ids
    assert report.set_version == DEFAULT_SET_VERSION
    for row in report.detectors:
        assert row.support > 0, row.detector_id
        assert row.matches > 0, row.detector_id
        assert row.precision is not None
        assert row.recall is not None


@pytest.mark.parametrize("category", sorted(GATED_CATEGORIES))
def test_gate_recall_is_one_end_to_end(report: QualityReport, category: str) -> None:
    rows = [e for e in report.end_to_end if e.category == category and e.context != CHAINED_CONTEXT]
    assert rows, f"no {category} spans in the corpus"
    failures = sorted(
        {(e.kind, e.context, e.failed or "leaked") for e in rows if e.leaked or e.failed}
    )
    redacted, support = report.e2e_recall(category, exclude_contexts=frozenset({CHAINED_CONTEXT}))
    assert not failures, (
        f"{category} recall {redacted}/{support} below 1.0; (kind, context, outcome): {failures}"
    )


@pytest.mark.xfail(strict=True, reason=_CHAINED_FIX)
def test_chained_label_context_leaves_no_value(report: QualityReport) -> None:
    rows = [e for e in report.end_to_end if e.context == CHAINED_CONTEXT]
    assert rows
    assert not [e for e in rows if e.leaked or e.failed]


# --- published table -------------------------------------------------------------------------


def test_runbook_carries_the_quality_table_for_this_detector_set() -> None:
    text = RUNBOOK.read_text(encoding="utf-8")
    assert text.count(TABLE_START) == 1
    assert text.count(TABLE_END) == 1
    block = text.split(TABLE_START, 1)[1].split(TABLE_END, 1)[0]
    assert TABLE_HEADER in block
    assert f"`{DEFAULT_SET_VERSION}`" in block, "rerun report_quality.py: detector set changed"
