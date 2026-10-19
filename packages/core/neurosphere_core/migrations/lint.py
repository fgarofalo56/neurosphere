"""Backwards-compatibility lint for migration steps (expand then contract).

A field may be removed only in a release strictly later than the one that deprecated it.
Also flags duplicate ids, duplicate or non-contiguous versions per scope, and missing ``down``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable

    from neurosphere_core.migrations.models import MigrationStep

__all__ = ["LintViolation", "MigrationLintError", "lint_migrations", "parse_release"]

_SEMVER = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)(?:-([0-9A-Za-z.-]+))?(?:\+[0-9A-Za-z.-]+)?$")


class MigrationLintError(ValueError):
    """Raised by the runner when the step list violates a lint rule."""

    def __init__(self, violations: list[LintViolation]) -> None:
        super().__init__("; ".join(f"{v.rule}: {v.message}" for v in violations))
        self.violations = violations


@dataclass(frozen=True)
class LintViolation:
    """One lint finding."""

    rule: str
    step_id: str
    message: str


def parse_release(release: str) -> tuple[int, int, int, int, str]:
    """Sortable key for a SemVer string; a pre-release sorts before its final release."""
    match = _SEMVER.match(release)
    if match is None:
        raise ValueError(f"release {release!r} is not SemVer")
    major, minor, patch, pre = match.groups()
    return (int(major), int(minor), int(patch), 0 if pre else 1, pre or "")


def lint_migrations(steps: Iterable[MigrationStep]) -> list[LintViolation]:
    """Return every violation; an empty list means the steps are clean."""
    all_steps = list(steps)
    out: list[LintViolation] = []

    seen: set[str] = set()
    for step in all_steps:
        if step.id in seen:
            out.append(LintViolation("duplicate_id", step.id, "step id is not unique"))
        seen.add(step.id)
        if step.down is None:
            out.append(LintViolation("missing_down", step.id, "step has no down function"))
        try:
            parse_release(step.release)
        except ValueError as exc:
            out.append(LintViolation("bad_release", step.id, str(exc)))

    scopes: dict[tuple[str, str], list[MigrationStep]] = {}
    for step in all_steps:
        scopes.setdefault((step.target.value, step.name), []).append(step)
    for (target, name), members in scopes.items():
        versions = [s.version for s in members]
        for step in members:
            if versions.count(step.version) > 1:
                out.append(
                    LintViolation("duplicate_version", step.id, f"version {step.version} repeated")
                )
        if sorted(set(versions)) != list(range(1, len(set(versions)) + 1)):
            out.append(
                LintViolation(
                    "non_contiguous_versions",
                    members[0].id,
                    f"{target}/{name} versions {sorted(versions)} are not contiguous from 1",
                )
            )
        out.extend(_removal_violations(members))
    return out


def _removal_violations(members: list[MigrationStep]) -> list[LintViolation]:
    out: list[LintViolation] = []
    for step in members:
        try:
            release = parse_release(step.release)
        except ValueError:
            continue  # reported as bad_release
        for path in step.removes:
            deprecated_in = []
            for other in members:
                if path not in other.deprecates:
                    continue
                try:
                    deprecated_in.append((parse_release(other.release), other.release))
                except ValueError:
                    continue
            if any(key >= release for key, _ in deprecated_in):
                out.append(
                    LintViolation(
                        "remove_not_after_deprecate",
                        step.id,
                        f"{path!r} is removed in release {step.release} but deprecated in "
                        "the same or a later release; removal needs a strictly later release",
                    )
                )
            elif not deprecated_in:
                out.append(
                    LintViolation(
                        "remove_without_deprecate",
                        step.id,
                        f"{path!r} is removed without an earlier deprecation",
                    )
                )
    return out
