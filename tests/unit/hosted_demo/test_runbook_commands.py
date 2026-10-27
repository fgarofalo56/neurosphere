"""PRP-32 item 8: the hosted-demo runbook only uses real subcommands and flags, and leaks no ids.

Parses the fenced code blocks of ``docs/deploy/hosted-demo.md``. The scripts' own parser builders
are imported (no ``az`` call, no approval needed: ``--help`` is gated, ``build_parser`` is not).
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

import pytest

ROOT = Path(__file__).resolve().parents[3]
GATES = ROOT / "scripts" / "gates"
RUNBOOK = ROOT / "docs" / "deploy" / "hosted-demo.md"
EVIDENCE_INDEX = ROOT / "docs" / "evidence" / "PRP-32" / "README.md"

GUID = re.compile(r"\b[0-9a-fA-F]{8}-(?:[0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}\b")
EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
SUBSCRIPTION_GUID = re.compile(r"/subscriptions/[0-9a-fA-F]{8}-", re.IGNORECASE)
FENCE = re.compile(r"^```[a-zA-Z]*\n(.*?)^```", re.DOTALL | re.MULTILINE)


def _load(name: str) -> ModuleType:
    if str(GATES) not in sys.path:
        sys.path.insert(0, str(GATES))
    spec = importlib.util.spec_from_file_location(f"_runbook_{name}", GATES / f"{name}.py")
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


def test_runbook_exists_and_has_mermaid() -> None:
    text = RUNBOOK.read_text(encoding="utf-8")
    assert "```mermaid" in text
    assert "estimate; verify with the Azure pricing calculator" in text


def test_hosted_demo_commands_are_real() -> None:
    subs = _subparsers(_load("hosted_demo").build_parser())
    seen: set[str] = set()
    for tokens in _commands():
        args = _usage(tokens, "hosted_demo")
        if args is None:
            continue
        assert args, f"hosted_demo.py without a subcommand: {tokens}"
        name = args[0]
        assert name in subs, f"unknown subcommand {name!r}"
        seen.add(name)
        unknown = _used_flags(args[1:]) - _flags(subs[name]) - {"--help"}
        assert not unknown, f"{name}: unknown flag(s) {sorted(unknown)}"
    # Every live step that has a subcommand is documented with a command.
    assert seen >= {
        "preflight",
        "plan",
        "deploy",
        "grant-model-access",
        "entra-redirect",
        "seed-access",
        "smoke",
        "teardown",
        "status",
    }


def test_hosted_demo_seed_flags_are_real() -> None:
    flags = _flags(_load("hosted_demo_seed").build_parser())
    found = 0
    for tokens in _commands():
        args = _usage(tokens, "hosted_demo_seed")
        if args is None:
            continue
        found += 1
        unknown = _used_flags(args) - flags - {"--help"}
        assert not unknown, f"hosted_demo_seed.py: unknown flag(s) {sorted(unknown)}"
    assert found >= 1


def test_shared_approval_tokens_are_documented_and_accepted() -> None:
    text = RUNBOOK.read_text(encoding="utf-8")
    for token in ("hub-subnet", "hub-pe", "hub-dns", "budget", "foundry-role", "entra-app"):
        assert token in text
    common = _load("_hosted_demo_common")
    tokens = common.parse_shared("hub-subnet,hub-pe,hub-dns,budget")
    assert {"hub-subnet", "hub-pe", "hub-dns", "budget"} <= set(tokens)


def _public_docs() -> list[Path]:
    files = [p for p in (ROOT / "docs" / "deploy").rglob("*") if p.is_file()]
    return [*files, EVIDENCE_INDEX]


@pytest.mark.parametrize("path", _public_docs(), ids=lambda p: p.name)
def test_no_ids_or_emails_in_public_docs(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    assert not GUID.search(text), f"{path.name}: contains a GUID"
    assert not EMAIL.search(text), f"{path.name}: contains an email address"
    assert not SUBSCRIPTION_GUID.search(text), f"{path.name}: contains /subscriptions/<guid>"
