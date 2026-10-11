"""Bad-event injection: manifest accuracy, configurable rates, and per-kind semantics."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from sandbox.config import BadEventRates
from sandbox.generate import generate
from sandbox.tests.conftest import make_config
from sandbox.tests.support import TELEMETRY_SCHEMA, read_json, read_ndjson, schema_valid


def _lines(directory: Path) -> list[str]:
    return (directory / "telemetry.ndjson").read_text(encoding="utf-8").splitlines()


def test_manifest_lines_point_at_the_right_events(pilot_dir: Path) -> None:
    lines = _lines(pilot_dir)
    entries = read_ndjson(pilot_dir / "bad-event-manifest.ndjson")
    assert entries
    assert len({e["line"] for e in entries}) == len(entries), "one entry per line"
    assert [e["line"] for e in entries] == sorted(e["line"] for e in entries)
    for entry in entries:
        doc = json.loads(lines[entry["line"] - 1])
        kind = entry["kind"]
        if kind == "duplicate":
            assert lines[entry["line"] - 1] == lines[entry["duplicate_of_line"] - 1]
            assert entry["duplicate_of_line"] < entry["line"]
        elif kind == "out_of_order":
            assert doc["event_id"] == entry["event_id"]
            assert doc["event_time"] == entry["event_time"]
        elif kind == "missing_optional":
            assert doc["event_id"] == entry["event_id"]
            assert not set(entry["dropped_fields"]) & set(doc)
            assert schema_valid(TELEMETRY_SCHEMA, doc)
        elif kind == "malformed":
            assert not schema_valid(TELEMETRY_SCHEMA, doc)
        else:
            raise AssertionError(kind)


def test_summary_counts_and_expectations(pilot_dir: Path) -> None:
    summary = read_json(pilot_dir / "bad-event-manifest.json")
    entries = read_ndjson(pilot_dir / "bad-event-manifest.ndjson")
    counted = Counter(e["kind"] for e in entries)
    assert summary["counts"] == {
        k: counted.get(k, 0) for k in ("duplicate", "out_of_order", "malformed", "missing_optional")
    }
    lines = _lines(pilot_dir)
    assert summary["expected"]["total_lines"] == len(lines)
    malformed = {e["line"] for e in entries if e["kind"] == "malformed"}
    valid = [ln for n, ln in enumerate(lines, start=1) if n not in malformed]
    assert len(valid) == len(lines) - summary["counts"]["malformed"]
    # Duplicates are byte-identical lines; missing-optional variants keep their own event_id.
    assert (
        len({json.loads(ln)["event_id"] for ln in valid})
        == summary["expected"]["valid_distinct_events"]
    )


def test_default_rates_are_small_and_fixed(pilot_dir: Path) -> None:
    summary = read_json(pilot_dir / "bad-event-manifest.json")
    total = summary["expected"]["total_lines"]
    defaults = BadEventRates()
    for kind, rate in (
        ("duplicate", defaults.duplicate),
        ("out_of_order", defaults.out_of_order),
        ("malformed", defaults.malformed),
        ("missing_optional", defaults.missing_optional),
    ):
        observed = summary["counts"][kind] / total
        assert 0.5 * rate < observed < 1.6 * rate, (kind, observed)
        assert summary["rates"][kind] == rate


def test_out_of_order_events_arrive_after_later_events(pilot_dir: Path) -> None:
    lines = _lines(pilot_dir)
    entries = read_ndjson(pilot_dir / "bad-event-manifest.ndjson")
    late = {e["line"] for e in entries if e["kind"] == "out_of_order"}
    labelled = {e["line"] for e in entries if e["kind"] in {"duplicate", "malformed"}}
    newest = ""
    late_behind = 0
    unlabelled = 0
    for n, raw in enumerate(lines, start=1):
        t = json.loads(raw).get("event_time", "")
        if n in late:
            late_behind += t < newest
        elif t < newest and n not in labelled:
            unlabelled += 1
        if n not in late and n not in labelled:
            newest = max(newest, t)
    # A held-back event can land in a quiet gap (overnight) and so not be behind anything.
    assert late_behind >= 0.9 * len(late)
    assert unlabelled == 0


def test_zero_rates_produce_clean_ordered_stream(tmp_path: Path) -> None:
    rates = BadEventRates(duplicate=0.0, out_of_order=0.0, malformed=0.0, missing_optional=0.0)
    generate(make_config(rates=rates), tmp_path)
    assert read_ndjson(tmp_path / "bad-event-manifest.ndjson") == []
    times = [json.loads(ln)["event_time"] for ln in _lines(tmp_path)]
    assert times == sorted(times)
    ids = [json.loads(ln)["event_id"] for ln in _lines(tmp_path)]
    assert len(ids) == len(set(ids))


def test_rates_are_configurable(tmp_path: Path) -> None:
    rates = BadEventRates(duplicate=0.0, out_of_order=0.0, malformed=0.2, missing_optional=0.0)
    generate(make_config(rates=rates), tmp_path)
    kinds = Counter(e["kind"] for e in read_ndjson(tmp_path / "bad-event-manifest.ndjson"))
    assert set(kinds) == {"malformed"}
    assert kinds["malformed"] > 100
