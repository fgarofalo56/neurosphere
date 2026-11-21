"""PRP-139 item 7: the real-tenant runbook only uses real subcommands and flags, and leaks no ids.

Parses the fenced code blocks of ``docs/deploy/hosted-real-tenant.md`` against the scripts' own
parser builders (no ``az`` call, no approval needed).
"""

from __future__ import annotations

import argparse
import importlib.util
import re
import shlex
import sys
from collections.abc import Iterator
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[3]
GATES = ROOT / "scripts" / "gates"
RUNBOOK = ROOT / "docs" / "deploy" / "hosted-real-tenant.md"
EVIDENCE_INDEX = ROOT / "docs" / "evidence" / "PRP-139" / "README.md"

GUID = re.compile(r"\b[0-9a-fA-F]{8}-(?:[0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}\b")
ZERO_GUID = "00000000-0000-0000-0000-000000000000"
# Built-in role definition ids verified against Microsoft Learn on 2026-11-21; public values.
ROLE_IDS = {
    "53ca6127-db72-4b80-b1b0-d745d6d5456d",
    "2a2b9908-6ea1-4ae2-8e65-a410df84e7d1",
    "3b03c2da-16b3-4a49-8834-0f8130efdd3b",
    "71522526-b88f-4d52-b57f-d31fc3546d0d",
}
EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
SUBSCRIPTION_GUID = re.compile(r"/subscriptions/[0-9a-fA-F]{8}-", re.IGNORECASE)
FENCE = re.compile(r"^```[a-zA-Z]*\n(.*?)^```", re.DOTALL | re.MULTILINE)
SHARED_FOUNDRY = "aifndry-loom-centralus"


def _load(name: str) -> ModuleType:
    if str(GATES) not in sys.path:
        sys.path.insert(0, str(GATES))
    spec = importlib.util.spec_from_file_location(f"_rt_runbook_{name}", GATES / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _commands() -> Iterator[list[str]]:
    """Every shell command in the fenced blocks, backslash continuations joined."""
    text = RUNBOOK.read_text(encoding="utf-8")
    for block in FENCE.findall(text):
        joined = re.sub(r"\\\n\s*", " ", block)
        for line in joined.splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                try:
                    yield shlex.split(line)
                except ValueError:
                    continue


def _usage(tokens: list[str], script: str) -> list[str] | None:
    for i, tok in enumerate(tokens):
        if tok.endswith(f"/{script}.py") or tok == f"{script}.py":
            return tokens[i + 1 :]
    return None


def _flags(parser: argparse.ArgumentParser) -> set[str]:
    return {opt for action in parser._actions for opt in action.option_strings}


def _subparsers(parser: argparse.ArgumentParser) -> dict[str, argparse.ArgumentParser]:
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            return dict(action.choices)
    raise AssertionError("no subcommands")


def _used_flags(args: list[str]) -> set[str]:
    return {a.split("=", 1)[0] for a in args if a.startswith("--")}


def _subcommand_of(args: list[str], names: set[str]) -> str:
    found = [a for a in args if a in names]
    assert found, f"no subcommand in {args}"
    return found[0]


def test_hosted_real_tenant_commands_are_real() -> None:
    subs = _subparsers(_load("hosted_real_tenant").build_parser())
    seen: set[str] = set()
    for tokens in _commands():
        args = _usage(tokens, "hosted_real_tenant")
        if args is None:
            continue
        name = args[0]
        assert name in subs, f"unknown subcommand {name!r}"
        seen.add(name)
        unknown = _used_flags(args[1:]) - _flags(subs[name]) - {"--help"}
        assert not unknown, f"{name}: unknown flag(s) {sorted(unknown)}"
        # Required options are present, so the real parser accepts the line.
        subs[name].parse_args(args[1:])
    assert seen == {"access-plan", "access-apply", "bootstrap-worker", "verify"}


def test_purge_commands_are_real() -> None:
    parser = _load("hosted_purge_synthetic").build_parser()
    subs = _subparsers(parser)
    seen: set[str] = set()
    for tokens in _commands():
        args = _usage(tokens, "hosted_purge_synthetic")
        if args is None:
            continue
        name = _subcommand_of(args, set(subs))
        seen.add(name)
        parser.parse_args(args)
    assert seen == {"plan", "apply"}


def test_hosted_demo_commands_are_real() -> None:
    parser = _load("hosted_demo").build_parser()
    subs = _subparsers(parser)
    seen: set[str] = set()
    for tokens in _commands():
        args = _usage(tokens, "hosted_demo")
        if args is None:
            continue
        name = args[0]
        assert name in subs, f"unknown subcommand {name!r}"
        seen.add(name)
        unknown = _used_flags(args[1:]) - _flags(subs[name]) - {"--help"}
        assert not unknown, f"{name}: unknown flag(s) {sorted(unknown)}"
        parsed = parser.parse_args(args)
        assert parsed.data_mode == "real-tenant"
        assert parsed.customer_id and parsed.customer_id != "synthco"
        assert parsed.budget_start_date == "2026-10-01"
    assert seen == {"plan", "deploy"}


def test_every_runbook_command_is_covered_by_a_parser() -> None:
    for tokens in _commands():
        line = " ".join(tokens)
        if "scripts/gates/" in line or "scripts/sandbox/" in line:
            assert any(
                _usage(tokens, s) is not None
                for s in ("hosted_real_tenant", "hosted_purge_synthetic", "hosted_demo")
            ), f"command not covered by a parser check: {line}"


def test_runbook_states_the_decided_facts() -> None:
    text = RUNBOOK.read_text(encoding="utf-8")
    # docs/deploy may hold no GUID (tests/unit/hosted_demo): role ids live in the evidence index.
    evidence = EVIDENCE_INDEX.read_text(encoding="utf-8")
    for role_id in ROLE_IDS:
        assert role_id in evidence
        assert role_id not in text
    for needle in (
        "--data-mode real-tenant",
        "--budget-start-date 2026-10-01",
        "--data-mode demo --customer-id synthco",
        "NS_HOSTED_DATA_MODE",
        "NS_HOSTED_CUSTOMER_ID",
        "NS_HOSTED_LOG_ANALYTICS_WORKSPACE_IDS",
        "NS_HOSTED_APIM_SERVICE_IDS",
        "UNVERIFIED",
        "10 minutes",
        "Not run by this PRP",
        "/admin/sources/connectors",
        "MSYS_NO_PATHCONV=1",
    ):
        assert needle in text, needle
    # The cut-over keeps the order of the PRP: access, deploy, bootstrap, connect, purge, verify.
    order = [
        "access-plan",
        "access-apply",
        "hosted_demo.py plan",
        "hosted_demo.py deploy",
        "bootstrap-worker",
        "### Step 4. Connect sources",
        "hosted_purge_synthetic.py \\\n  --registration temp/hosted-demo/registration.json \\\n  plan",  # noqa: E501
        "apply \\\n  --confirm",
        "hosted_real_tenant.py verify",
    ]
    positions = [text.index(item, text.index("## 3. Cut-over")) for item in order]
    assert positions == sorted(positions)


def test_shared_foundry_account_only_in_the_not_a_default_sentence() -> None:
    for path in (RUNBOOK, EVIDENCE_INDEX):
        text = path.read_text(encoding="utf-8")
        hits = [m.start() for m in re.finditer(re.escape(SHARED_FOUNDRY), text)]
        if path == EVIDENCE_INDEX:
            assert not hits
            continue
        assert len(hits) == 1
        sentence = re.sub(r"\s+", " ", text[max(0, hits[0] - 80) : hits[0] + 200])
        assert "never a default target" in sentence


def test_no_placeholder_looks_like_a_real_id() -> None:
    for path in (RUNBOOK, EVIDENCE_INDEX):
        text = path.read_text(encoding="utf-8")
        for guid in GUID.findall(text):
            assert guid.lower() in ROLE_IDS or guid == ZERO_GUID, f"{path.name}: {guid}"
        assert not EMAIL.search(text), f"{path.name}: contains an email address"
        assert not SUBSCRIPTION_GUID.search(text), f"{path.name}: contains /subscriptions/<guid>"
        assert not re.search(r"https?://[\w.-]+\.(?:azure|windows)\.\w+", text), path.name
