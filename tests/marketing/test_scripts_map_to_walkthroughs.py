"""Persona demo scripts must map to real walkthroughs, sandbox scenarios and routes."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "marketing" / "scripts"
PERSONAS = ("viewer", "analyst", "steward", "admin", "auditor")
BANNED = re.compile(
    r"\b(authorized|ATO|FedRAMP compliant|parity|unique|guaranteed)\b", re.IGNORECASE
)
NEGATION = re.compile(r"\b(no|not|never|without|nothing|n't)\b", re.IGNORECASE)


def _front_matter(path: Path) -> tuple[dict[str, object], str]:
    text = path.read_text(encoding="utf-8")
    match = re.match(r"---\n(.*?)\n---\n(.*)", text, re.DOTALL)
    assert match, f"{path.name}: missing front matter"
    data: dict[str, object] = {}
    key = ""
    for line in match.group(1).splitlines():
        if line.startswith("  - "):
            value = data[key]
            assert isinstance(value, list)
            value.append(line[4:].strip().strip('"'))
        elif ":" in line:
            key, _, rest = line.partition(":")
            data[key] = rest.strip() if rest.strip() else []
    return data, match.group(2)


def _sandbox_scenarios() -> set[str]:
    world = (ROOT / "sandbox" / "world.py").read_text(encoding="utf-8")
    anomaly = set(
        re.findall(
            r'"(cost_spike|latency_regression|unused_agent|duplicate_agent_candidates)"', world
        )
    )
    # Bad-event scenario: a generator module of the same name exists.
    modules = {p.stem for p in (ROOT / "sandbox").glob("*.py")}
    return anomaly | {m for m in modules if m == "bad_events"}


def _routes() -> set[str]:
    manifest = ROOT / "frontend" / "src" / "app" / "route-manifest.json"
    return set(json.loads(manifest.read_text(encoding="utf-8"))["routes"])


@pytest.mark.parametrize("persona", PERSONAS)
def test_script_maps_to_walkthrough_and_scenario(persona: str) -> None:
    path = SCRIPTS / f"{persona}.md"
    assert path.is_file()
    meta, body = _front_matter(path)
    assert meta["status"] == "draft"
    assert meta["persona"] == persona
    walkthrough = ROOT / str(meta["walkthrough"])
    assert walkthrough.is_file()
    scenario = str(meta["sandbox_scenario"])
    assert f"Sandbox scenario: `{scenario}`" in walkthrough.read_text(encoding="utf-8")
    assert scenario in _sandbox_scenarios()
    assert meta["claims"] and meta["permissions"]
    for heading in ("## Steps", "## Permissions", "## Isolation"):
        assert heading in body
    steps = re.findall(r"^\d+\. ", body, re.MULTILINE)
    assert steps
    assert body.count("- Expected:") == len(steps)
    assert body.count("- Permission:") == len(steps)


@pytest.mark.parametrize("persona", PERSONAS)
def test_steps_reference_only_merged_routes(persona: str) -> None:
    _, body = _front_matter(SCRIPTS / f"{persona}.md")
    demo = body.split("## Steps", 1)[1].split("## Permissions", 1)[0]
    used = set(re.findall(r"`(/[a-z][a-z0-9/_<>-]*)`", demo))
    routes = _routes() | {f"/workspaces/{persona}"}
    assert used
    assert used <= routes, used - routes


def test_map_lists_every_script() -> None:
    text = (SCRIPTS / "feature-persona-map.md").read_text(encoding="utf-8")
    for persona in PERSONAS:
        assert f"]({persona}.md)" in text


@pytest.mark.parametrize("name", [*(f"{p}.md" for p in PERSONAS), "feature-persona-map.md"])
def test_no_absolute_claims_or_em_dashes(name: str) -> None:
    text = (SCRIPTS / name).read_text(encoding="utf-8")
    assert "—" not in text
    for line in text.splitlines():
        if BANNED.search(line):
            assert NEGATION.search(line), f"{name}: {line}"
