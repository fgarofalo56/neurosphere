"""The dashboards reference only the five SLO metric names (PRP-05 item 4 names)."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

SLO_METRICS = frozenset(
    {
        "ns.api.request.duration",
        "ns.api.request.errors",
        "ns.dashboard.query.duration",
        "ns.catalog.query.duration",
        "ns.map.freshness.lag",
    }
)
OBS_DIR = Path(__file__).resolve().parents[3] / "infra" / "observability"
FILES = ["grafana-slo-dashboard.json", "azure-workbook-slo.json"]
NS_TOKEN = re.compile(r"\bns\.[A-Za-z0-9_]+(?:\.[A-Za-z0-9_]+)*")


@pytest.mark.parametrize("name", FILES)
def test_dashboard_references_only_slo_metrics(name: str) -> None:
    text = (OBS_DIR / name).read_text(encoding="utf-8")
    json.loads(text)  # parses
    found = set(NS_TOKEN.findall(text))
    assert found == SLO_METRICS


def test_slo_doc_lists_all_metric_names() -> None:
    doc = (OBS_DIR.parents[1] / "docs" / "ops" / "slo.md").read_text(encoding="utf-8")
    for metric in SLO_METRICS:
        assert metric in doc
