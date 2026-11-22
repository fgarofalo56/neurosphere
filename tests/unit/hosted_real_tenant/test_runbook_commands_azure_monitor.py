"""PRP-141 item 7: every command in the Azure Monitor AI runbook parses offline, no real ids.

Parses the fenced code blocks of ``docs/runbooks/azure-monitor-ai-telemetry.md`` against the
script's own parser (no ``az`` call, no approval needed).
"""

from __future__ import annotations

import re
import shlex
from pathlib import Path

from test_real_tenant_runbook_commands import (
    EMAIL,
    FENCE,
    GUID,
    SUBSCRIPTION_GUID,
    _flags,
    _load,
    _subparsers,
    _usage,
)

ROOT = Path(__file__).resolve().parents[3]
RUNBOOK = ROOT / "docs" / "runbooks" / "azure-monitor-ai-telemetry.md"
EVIDENCE = ROOT / "docs" / "evidence" / "PRP-141" / "README.md"
# The built-in Log Analytics Data Reader role id: a public value PRP-139 already assigns.
ALLOWED_GUIDS = {"3b03c2da-16b3-4a49-8834-0f8130efdd3b"}
REASON_CODES = (
    "source_access_denied",
    "query_budget_exhausted",
    "event_budget_exhausted",
    "rate_limited",
    "stalled",
    "ingest_failed",
    "cloud_mismatch",
    "refused_government_unverified",
    "source_unreachable",
    "partial_results",
    "not_configured",
)


def _commands() -> list[list[str]]:
    out: list[list[str]] = []
    for block in FENCE.findall(RUNBOOK.read_text(encoding="utf-8")):
        joined = re.sub(r"\\\n\s*", " ", block)
        for line in joined.splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                out.append(shlex.split(line))
    return out


def test_every_gate_command_parses_against_the_real_parser() -> None:
    parser = _load("hosted_real_tenant").build_parser()
    subs = _subparsers(parser)
    seen: set[str] = set()
    for tokens in _commands():
        args = _usage(tokens, "hosted_real_tenant")
        assert args is not None, f"a command that is not a gate script: {tokens}"
        name = args[0]
        assert name in subs, f"unknown subcommand {name!r}"
        seen.add(name)
        used = {a.split("=", 1)[0] for a in args[1:] if a.startswith("--")}
        assert not used - _flags(subs[name]) - {"--help"}
        subs[name].parse_args(args[1:])
    assert seen == {"access-plan", "verify"}


def test_runbook_covers_every_reason_code_and_the_decided_facts() -> None:
    text = RUNBOOK.read_text(encoding="utf-8")
    for code in REASON_CODES:
        assert f"`{code}`" in text, code
    for needle in (
        "logAnalyticsWorkspaceIds",
        "Log Analytics Data Reader",
        "Privileged Monitoring Data Reader",
        "NS_AZURE_MONITOR_AI_",
        "workers.roles",
        "no hot reload",
        "one path per workload",
        "Copilot Studio",
        "UNVERIFIED",
        "CONTENT_DENYLIST",
        "Rollback",
    ):
        assert needle.lower() in text.lower(), needle


def test_no_placeholder_looks_like_a_real_id() -> None:
    for path in (RUNBOOK, EVIDENCE):
        text = path.read_text(encoding="utf-8")
        for guid in GUID.findall(text):
            assert guid.lower() in ALLOWED_GUIDS, f"{path.name}: {guid}"
        assert not EMAIL.search(text), path.name
        assert not SUBSCRIPTION_GUID.search(text), path.name
        assert not re.search(r"https?://[\w.-]+\.(?:azure|windows)\.\w+", text), path.name
    assert "<workspace-resource-id>" in RUNBOOK.read_text(encoding="utf-8")


def test_evidence_index_keeps_every_row_open() -> None:
    text = EVIDENCE.read_text(encoding="utf-8")
    rows = [line for line in text.splitlines() if re.match(r"^\| [1-5] \|", line)]
    assert len(rows) == 5
    assert all(line.rstrip().endswith("OPEN |") for line in rows)
    assert "PASS" in text and "**OPEN**" in text
