"""Telemetry `classification` is stamped per agent; the fail-closed (null) path stays exercised."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

from neurosphere_contracts.telemetry.v1.telemetry_event import TelemetryEvent
from neurosphere_workers.archive.serialize import redact_record

from sandbox.generate import generate
from sandbox.tests.conftest import make_config
from sandbox.tests.support import REPO_ROOT, read_ndjson

CLASSES = {"public", "internal", "cui", "restricted"}
DATASETS = REPO_ROOT / "sandbox" / "evaluation" / "data" / "datasets.json"


def _valid_events(directory: Path) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for doc in read_ndjson(directory / "telemetry.ndjson"):
        try:
            TelemetryEvent.model_validate(doc)
        except ValueError:
            continue  # seeded bad events are covered elsewhere
        out.append(doc)
    return out


def test_all_classes_and_null_appear_in_default_generation(tiny_dir: Path) -> None:
    counts = Counter(e.get("classification") for e in _valid_events(tiny_dir))
    assert CLASSES <= set(counts), counts
    assert counts[None] > 0, counts


def test_classification_is_per_agent(tiny_dir: Path) -> None:
    per_agent: dict[str, set[Any]] = {}
    for e in _valid_events(tiny_dir):
        per_agent.setdefault(e["canonical_agent_id"], set()).add(e.get("classification"))
    assert all(len(v) == 1 for v in per_agent.values())


def test_vocabulary_matches_evaluation_registry(tiny_dir: Path) -> None:
    text = DATASETS.read_text(encoding="utf-8")
    registry = {m for m in CLASSES if f'"classification": "{m}"' in text}
    assert registry == CLASSES
    used = {e.get("classification") for e in _valid_events(tiny_dir)} - {None}
    assert used <= registry


def test_same_seed_same_classification(tmp_path: Path) -> None:
    generate(make_config(seed=7), tmp_path / "a")
    generate(make_config(seed=7), tmp_path / "b")
    a = [(e["event_id"], e.get("classification")) for e in _valid_events(tmp_path / "a")]
    b = [(e["event_id"], e.get("classification")) for e in _valid_events(tmp_path / "b")]
    assert a == b


def test_classification_survives_archive_redaction(tiny_dir: Path) -> None:
    labelled = [e for e in _valid_events(tiny_dir) if e.get("classification")]
    assert labelled
    for event in labelled[:50]:
        record = json.loads(json.dumps(event))
        redacted = redact_record(record, b"k" * 32)
        assert redacted["classification"] == event["classification"]
