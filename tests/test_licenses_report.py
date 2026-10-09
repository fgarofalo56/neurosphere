"""Tests for scripts/licenses_report.py using fixture lockfiles and synthetic local metadata."""

from __future__ import annotations

import json
import runpy
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "licenses"
NS = runpy.run_path(str(ROOT / "scripts" / "licenses_report.py"))
main = NS["main"]


def add_python(tmp: Path, name: str, version: str, **headers: str) -> None:
    dist = tmp / "venv" / "Lib" / "site-packages" / f"{name}-{version}.dist-info"
    dist.mkdir(parents=True, exist_ok=True)
    lines = ["Metadata-Version: 2.4", f"Name: {name}", f"Version: {version}"]
    lines += [f"{k.replace('_', '-')}: {v}" for k, v in headers.items()]
    (dist / "METADATA").write_text("\n".join(lines) + "\n", encoding="utf-8")


def add_npm(tmp: Path, name: str, version: str, licence: object | None) -> None:
    store = tmp / "node_modules" / ".pnpm" / f"{name.replace('/', '+')}@{version}"
    pkg_dir = store / "node_modules" / name
    pkg_dir.mkdir(parents=True, exist_ok=True)
    manifest: dict[str, object] = {"name": name, "version": version}
    if licence is not None:
        manifest["license"] = licence
    (pkg_dir / "package.json").write_text(json.dumps(manifest), encoding="utf-8")


def run(tmp: Path, fixture: str, *extra: str) -> int:
    args = ["--output", str(tmp / "licenses.md"), "--adr", str(tmp / "no-adr.md")]
    args += ["--venv", str(tmp / "venv"), "--node-modules", str(tmp / "node_modules")]
    lock_dir = FIXTURES / fixture
    for flag, fname in (("--uv-lock", "uv.lock"), ("--pnpm-lock", "pnpm-lock.yaml")):
        args += [flag, str(lock_dir / fname if (lock_dir / fname).is_file() else tmp / "absent")]
    return main([*args, *extra])


def good_tree(tmp: Path) -> None:
    add_python(tmp, "hypothesis", "6.168.0", License_Expression="MPL-2.0")
    add_python(tmp, "sortedcontainers", "2.4.0", License="Apache-2.0")
    add_npm(tmp, "left-pad", "1.3.0", "MIT")
    add_npm(tmp, "@scope/dev-tool", "2.0.1", {"type": "ISC"})


def test_good_fixture_passes_and_hypothesis_is_dev_only(tmp_path: Path) -> None:
    good_tree(tmp_path)
    assert run(tmp_path, "good") == 0
    text = (tmp_path / "licenses.md").read_text(encoding="utf-8")
    assert "| hypothesis | 6.168.0 | MPL-2.0 | dev-only |" in text
    assert "| sortedcontainers | 2.4.0 | Apache-2.0 | dev-only |" in text
    assert "| left-pad | 1.3.0 | MIT | runtime |" in text
    assert "| @scope/dev-tool | 2.0.1 | ISC | dev-only |" in text
    assert "| fixture-app | 0.0.0 | first-party | first-party |" in text


def test_check_is_idempotent_and_detects_stale_register(tmp_path: Path) -> None:
    good_tree(tmp_path)
    assert run(tmp_path, "good") == 0
    assert run(tmp_path, "good", "--check") == 0
    assert run(tmp_path, "good", "--check") == 0
    register = tmp_path / "licenses.md"
    register.write_text(register.read_text(encoding="utf-8") + "\nstale edit\n", encoding="utf-8")
    assert run(tmp_path, "good", "--check") == 1


def test_check_fails_when_register_is_missing(tmp_path: Path) -> None:
    good_tree(tmp_path)
    assert run(tmp_path, "good", "--check") == 1


def test_unresolvable_licence_is_unknown_and_fails(tmp_path: Path, capsys) -> None:
    good_tree(tmp_path)
    add_npm(tmp_path, "left-pad", "1.3.0", None)
    assert run(tmp_path, "good") == 1
    out = capsys.readouterr().out
    assert "npm:left-pad@1.3.0" in out and "UNKNOWN" in out
    assert "| left-pad | 1.3.0 | UNKNOWN |" in (tmp_path / "licenses.md").read_text(
        encoding="utf-8"
    )


def test_missing_metadata_is_unknown_not_permissive(tmp_path: Path) -> None:
    assert run(tmp_path, "good") == 1
    assert "UNKNOWN" in (tmp_path / "licenses.md").read_text(encoding="utf-8")


def test_unreadable_licence_text_is_unknown(tmp_path: Path) -> None:
    good_tree(tmp_path)
    add_npm(tmp_path, "left-pad", "1.3.0", "SEE LICENSE IN LICENSE.txt")
    assert run(tmp_path, "good") == 1


def test_copyleft_fails_then_passes_when_allowlisted_with_reason(tmp_path: Path) -> None:
    good_tree(tmp_path)
    add_npm(tmp_path, "left-pad", "1.3.0", "GPL-3.0-only")
    assert run(tmp_path, "good") == 1
    NS["ALLOWLIST"]["left-pad"] = "test reason"
    try:
        assert run(tmp_path, "good") == 0
    finally:
        NS["ALLOWLIST"].pop("left-pad")


def test_mpl_runtime_fails_but_dev_only_passes(tmp_path: Path) -> None:
    good_tree(tmp_path)
    add_npm(tmp_path, "left-pad", "1.3.0", "MPL-2.0")  # runtime package
    assert run(tmp_path, "good") == 1


def test_allowlist_cannot_hide_unknown(tmp_path: Path) -> None:
    good_tree(tmp_path)
    add_npm(tmp_path, "left-pad", "1.3.0", None)
    NS["ALLOWLIST"]["left-pad"] = "test reason"
    try:
        assert run(tmp_path, "good") == 1
    finally:
        NS["ALLOWLIST"].pop("left-pad")


def test_cosmograph_fixture_fails_even_with_a_permissive_claim(tmp_path: Path, capsys) -> None:
    add_npm(tmp_path, "@cosmograph/cosmograph", "2.1.0", "CC-BY-NC-4.0")
    assert run(tmp_path, "cosmograph", "--check") == 1
    assert "denied" in capsys.readouterr().out

    add_npm(tmp_path, "@cosmograph/cosmograph", "2.1.0", "MIT")
    assert run(tmp_path, "cosmograph") == 1


@pytest.mark.parametrize(
    ("expr", "dev_only", "ok"),
    [
        ("MIT", False, True),
        ("MIT OR GPL-3.0-only", False, True),
        ("MIT AND GPL-3.0-only", False, False),
        ("(MIT OR Apache-2.0) AND ISC", False, True),
        ("Apache-2.0 WITH LLVM-exception", False, True),
        ("MPL-2.0", True, True),
        ("MPL-2.0", False, False),
        ("CC-BY-NC-4.0", True, False),
        ("LicenseRef-EULA", False, False),
    ],
)
def test_expression_policy(expr: str, dev_only: bool, ok: bool) -> None:
    assert NS["expression_ok"](expr, dev_only) is ok


def test_python_classifier_fallback(tmp_path: Path) -> None:
    add_python(
        tmp_path, "hypothesis", "6.168.0", Classifier="License :: OSI Approved :: BSD License"
    )
    dists = NS["find_site_packages"](tmp_path / "venv")
    deps = NS["read_uv_lock"](FIXTURES / "good" / "uv.lock", dists, {})
    by_name = {d.name: d for d in deps}
    assert by_name["hypothesis"].licence == "BSD"
    assert by_name["sortedcontainers"].licence == "UNKNOWN"


def test_not_installed_package_uses_committed_register_for_same_version(tmp_path: Path) -> None:
    carried = {("npm", "left-pad", "1.3.0"): "MIT"}
    deps = NS["read_pnpm_lock"](FIXTURES / "good" / "pnpm-lock.yaml", tmp_path / "none", carried)
    assert {d.name: d.licence for d in deps}["left-pad"] == "MIT"
    stale = {("npm", "left-pad", "9.9.9"): "MIT"}
    deps = NS["read_pnpm_lock"](FIXTURES / "good" / "pnpm-lock.yaml", tmp_path / "none", stale)
    assert {d.name: d.licence for d in deps}["left-pad"] == "UNKNOWN"


def test_adr_appendix_is_spliced_and_checked(tmp_path: Path) -> None:
    good_tree(tmp_path)
    adr = tmp_path / "adr.md"
    adr.write_text(f"head\n\n{NS['BEGIN']}\nold\n{NS['END']}\n\ntail\n", encoding="utf-8")
    extra = ["--adr", str(adr)]
    assert run(tmp_path, "good", *extra) == 0
    text = adr.read_text(encoding="utf-8")
    assert text.startswith("head") and text.rstrip().endswith("tail")
    assert "| hypothesis | 6.168.0 | MPL-2.0 |" in text and "old" not in text
    assert run(tmp_path, "good", "--check", *extra) == 0
    adr.write_text(text.replace("left-pad", "left-padX", 1), encoding="utf-8")
    assert run(tmp_path, "good", "--check", *extra) == 1


def test_splice_requires_markers() -> None:
    with pytest.raises(ValueError):
        NS["splice_adr"]("no markers here", "block")


def test_real_repo_register_is_current() -> None:
    """The committed docs/licenses.md and ADR-0002 appendix match the committed lockfiles."""
    assert main(["--check"]) == 0
