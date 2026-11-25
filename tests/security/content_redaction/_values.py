"""Runtime value sources for the PRP-101 item 7 security suite.

The seeded credential generators live in ``packages/core/tests/content_detectors/synth.py``.
That directory is a package named ``content_detectors`` on its own ``sys.path`` root, so it is
loaded here by file path under a unique module name: importing it by package name from this
tree would depend on pytest's rootdir insertion order and could shadow a same-named package.

No credential-shaped, card-shaped or SSN-shaped literal lives in this file: every value is
built at runtime from a seeded ``random.Random`` (gitleaks and ``.githooks`` scan diffs).
"""

from __future__ import annotations

import base64
import hashlib
import importlib.util
import logging
import random
import sys
from collections.abc import Callable, Iterable, Iterator, Mapping
from pathlib import Path
from typing import Any, Final, cast

import pytest
from neurosphere_core.classification import (
    ALL_CATEGORIES,
    Category,
    placeholder,
)

_SYNTH_PATH: Final = (
    Path(__file__).resolve().parents[3]
    / "packages"
    / "core"
    / "tests"
    / "content_detectors"
    / "synth.py"
)
_SYNTH_NAME: Final = "ns_prp101_item7_synth"


def _load_synth() -> Any:
    if _SYNTH_NAME in sys.modules:
        return sys.modules[_SYNTH_NAME]
    spec = importlib.util.spec_from_file_location(_SYNTH_NAME, _SYNTH_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[_SYNTH_NAME] = module
    spec.loader.exec_module(module)
    return module


_SYNTH: Final = _load_synth()

CREDENTIAL_GENERATORS: Final = cast(
    "Mapping[str, Callable[[random.Random], str]]", _SYNTH.CREDENTIAL_GENERATORS
)
EXPECTED_CATEGORY: Final = cast("Mapping[str, str]", _SYNTH.EXPECTED_CATEGORY)
secret_value: Final = cast("Callable[[str, str], str]", _SYNTH.secret_value)

FRAGMENT: Final = 6
ALL_PLACEHOLDERS: Final = tuple(placeholder(cast("Category", c)) for c in sorted(ALL_CATEGORIES))


def card(rng: random.Random) -> str:
    """A Luhn-valid 16-digit number."""
    body = [4] + [rng.randrange(10) for _ in range(14)]
    total = 0
    for i, digit in enumerate(reversed(body)):
        doubled = digit * 2 if i % 2 == 0 else digit
        total += doubled - 9 if doubled > 9 else doubled
    return "".join(map(str, body)) + str((10 - total % 10) % 10)


def ssn(rng: random.Random) -> str:
    """Area/group/serial within the accepted ranges, dash separated."""
    area = rng.choice([a for a in range(1, 900) if a != 666])
    return f"{area:03d}-{rng.randint(1, 99):02d}-{rng.randint(1, 9999):04d}"


def email(rng: random.Random) -> str:
    local = "".join(rng.choice("abcdefghijklmnopqrstuvwxyz") for _ in range(rng.randint(6, 12)))
    return f"{local}{rng.randrange(1000, 9999)}@example.org"


def grams(value: str, size: int = FRAGMENT) -> set[str]:
    """Every ``size``-character window of ``value`` (the whole value when shorter)."""
    if len(value) <= size:
        return {value}
    return {value[i : i + size] for i in range(len(value) - size + 1)}


def leaked_fragments(secret: str, haystack: str, benign: Iterable[str]) -> set[str]:
    """6+ char windows of ``secret`` present in ``haystack`` and not explained by ``benign``.

    ``benign`` is text the caller wrote around the secret (context template, kept labels,
    placeholders); a window that also occurs there is not evidence of a leak.
    """
    allowed: set[str] = set()
    for text in benign:
        allowed |= grams(text)
    return {g for g in grams(secret) if g in haystack and g not in allowed}


def derived_forms(secret: str) -> dict[str, str]:
    """Encodings of ``secret`` a careless placeholder or log line might carry."""
    raw = secret.encode("utf-8")
    forms: dict[str, str] = {}
    for name in ("sha256", "sha1", "md5"):
        digest = hashlib.new(name, raw).hexdigest()
        forms[name] = digest
        forms[f"{name}_prefix8"] = digest[:8]
        forms[f"{name}_upper_prefix8"] = digest[:8].upper()
    b64 = base64.b64encode(raw).decode("ascii")
    b64url = base64.urlsafe_b64encode(raw).decode("ascii")
    forms["base64"] = b64
    forms["base64url"] = b64url
    forms["base64_stripped"] = b64.rstrip("=")
    forms["base64url_stripped"] = b64url.rstrip("=")
    return forms


def length_decorations(secret: str) -> list[str]:
    """The secret's length attached to a placeholder (``...]]:42``, ``...]](42)``, ...)."""
    n = len(secret)
    out: list[str] = []
    for token in ALL_PLACEHOLDERS:
        out += [f"{token}:{n}", f"{token}({n})", f"{token} ({n})", f"{token}[{n}]"]
        out += [f"{token}#{n}", f"{token}/{n}", f"{token}-{n}", f"{token[:-2]}:{n}]]"]
        out += [f"{n}:{token}", f"({n}){token}", f"[{n}]{token}", f"{token[:2]}{n}:{token[2:]}"]
    return out


def log_text(records: Iterable[logging.LogRecord]) -> str:
    """Everything a handler could render from ``records``: message, raw args, exc_text."""
    parts: list[str] = []
    for record in records:
        parts.append(str(record.msg))
        parts.append(repr(record.args))
        try:
            parts.append(record.getMessage())
        except Exception:
            pass
        if record.exc_info:
            parts.append(logging.Formatter().formatException(record.exc_info))
        if record.exc_text:
            parts.append(record.exc_text)
        if record.stack_info:
            parts.append(record.stack_info)
    return "\n".join(parts)


def capture_all_loggers(caplog: pytest.LogCaptureFixture) -> Iterator[None]:
    """Route every existing logger at DEBUG into ``caplog`` (root plus named loggers)."""
    caplog.set_level(logging.DEBUG)
    manager = logging.Logger.manager
    restore: list[tuple[logging.Logger, int, bool]] = []
    for name in list(manager.loggerDict):
        logger = logging.getLogger(name)
        restore.append((logger, logger.level, logger.propagate))
        logger.setLevel(logging.DEBUG)
        logger.propagate = True
    try:
        yield
    finally:
        for logger, level, propagate in restore:
            logger.setLevel(level)
            logger.propagate = propagate
