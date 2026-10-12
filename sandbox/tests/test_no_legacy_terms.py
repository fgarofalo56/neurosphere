"""Deny-list over generated output and source: no procurement vocabulary, no personal data."""

from __future__ import annotations

import ast
import re
from pathlib import Path

from sandbox.tests.support import ALL_FILES

SANDBOX_DIR = Path(__file__).resolve().parents[1]

LEGACY = re.compile(
    r"vendor|purchase[ _-]?order|\bpo[ _-]?number|\bmaterials?\b|artemis|procurement|supplier",
    re.IGNORECASE,
)
EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
SSN = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
PHONE = re.compile(r"(?<!\d)(?:\+?1[ -.])?\(?\d{3}\)?[ -.]\d{3}[ -.]\d{4}(?!\d)")
STREET = re.compile(r"\b\d{1,5} [A-Z][a-z]+ (Street|St|Avenue|Ave|Road|Rd|Lane|Blvd)\b")
NAME_KEYS = re.compile(r'"(first_name|last_name|full_name|email|upn|phone|ssn|address)"')


def test_no_legacy_or_personal_terms_in_output(tiny_dir: Path, pilot_dir: Path) -> None:
    everything = (
        ("legacy", LEGACY),
        ("email", EMAIL),
        ("ssn", SSN),
        ("phone", PHONE),
        ("street", STREET),
        ("name-key", NAME_KEYS),
    )
    cheap = (("legacy", LEGACY), ("email", EMAIL), ("ssn", SSN), ("name-key", NAME_KEYS))
    # The slower phone/street patterns run on tiny only; pilot gets the fast subset.
    for directory, patterns in ((tiny_dir, everything), (pilot_dir, cheap)):
        for name in ALL_FILES:
            text = (directory / name).read_text(encoding="utf-8")
            for label, pattern in patterns:
                match = pattern.search(text)
                assert match is None, f"{label} term {match and match.group(0)!r} in {name}"


def test_no_legacy_terms_in_generator_source() -> None:
    for path in SANDBOX_DIR.glob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert LEGACY.search(text) is None, path.name


def test_generator_does_not_import_services_or_wall_clock() -> None:
    for path in SANDBOX_DIR.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom | ast.Import):
                names = (
                    [node.module or ""]
                    if isinstance(node, ast.ImportFrom)
                    else [a.name for a in node.names]
                )
                for mod in names:
                    assert not mod.startswith(
                        ("services", "neurosphere_api", "neurosphere_workers")
                    ), (path.name, mod)
            if isinstance(node, ast.Attribute) and node.attr in {"now", "utcnow", "uuid4", "today"}:
                raise AssertionError(f"{path.name}: nondeterministic call .{node.attr}")
