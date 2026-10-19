"""Shared prompt-injection and overscope corpus plus harness (PRP-12 item 4).

Consumers (PRP-19 copilot, PRP-22 MCP) import from here and supply their own adapter; they add
cases by PR to ``corpus.json`` and never fork it. See ``README.md``.
"""

from .harness import (
    Adapter,
    AdapterResult,
    AsyncAdapter,
    CaseResult,
    CorpusReport,
    Observation,
    ObservedOutcome,
    arun_corpus,
    run_corpus,
)
from .schema import CORPUS_PATH, Category, InjectionCase, ScopeFixture, load_corpus

__all__ = [
    "CORPUS_PATH",
    "Adapter",
    "AdapterResult",
    "AsyncAdapter",
    "CaseResult",
    "Category",
    "CorpusReport",
    "InjectionCase",
    "Observation",
    "ObservedOutcome",
    "ScopeFixture",
    "arun_corpus",
    "load_corpus",
    "run_corpus",
]
