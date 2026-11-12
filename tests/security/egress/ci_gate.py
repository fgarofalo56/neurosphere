"""Skip locally, fail under CI, when a tool the egress proof needs is missing.

A skipped scan in CI is a silent hole (issue #100), so GitHub's ``CI=true`` turns the skip into a
failure. Static and compose only; in-cluster proof OPEN (no Government subscription, D7).
"""

from __future__ import annotations

import os
import shutil
from typing import NoReturn

import pytest


def in_ci() -> bool:
    """True when the ``CI`` environment variable is set to anything but a falsey value."""
    return os.environ.get("CI", "").strip().lower() not in ("", "0", "false", "no")


def skip_or_fail(reason: str) -> NoReturn:
    """Fail the test under CI, skip it everywhere else."""
    if in_ci():
        pytest.fail(f"{reason} (CI is set: a missing tool must not skip the check)")
    pytest.skip(reason)


def require_tool(name: str, reason: str) -> str:
    """Return the absolute path of ``name`` or skip/fail with ``reason``."""
    exe = shutil.which(name)
    if exe is None:
        skip_or_fail(reason)
    return exe
