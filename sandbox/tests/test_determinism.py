"""Same seed + epoch => byte-identical output; different seeds differ; clouds never mix."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from sandbox.config import DEFAULT_EPOCH, PROFILES, GenerateConfig
from sandbox.generate import generate
from sandbox.tests.conftest import make_config
from sandbox.tests.support import ALL_FILES, REPO_ROOT, tree_hashes


def test_same_seed_is_byte_identical(tmp_path: Path) -> None:
    generate(make_config(seed=7), tmp_path / "a")
    generate(make_config(seed=7), tmp_path / "b")
    assert tree_hashes(tmp_path / "a") == tree_hashes(tmp_path / "b")


def test_identical_across_processes(tmp_path: Path) -> None:
    """A fresh interpreter (different hash randomisation) must produce the same bytes."""
    for name in ("p1", "p2"):
        subprocess.run(  # noqa: S603 - fixed argv, no shell, our own module
            [
                sys.executable,
                "-m",
                "sandbox.generate",
                "--seed",
                "7",
                "--profile",
                "tiny",
                "--cloud",
                "commercial",
                "--out",
                str(tmp_path / name),
            ],
            check=True,
            cwd=REPO_ROOT,
            capture_output=True,
        )
    assert tree_hashes(tmp_path / "p1") == tree_hashes(tmp_path / "p2")
    generate(make_config(seed=7), tmp_path / "api")
    assert tree_hashes(tmp_path / "p1") == tree_hashes(tmp_path / "api")


def test_different_seeds_differ(tmp_path: Path) -> None:
    generate(make_config(seed=1), tmp_path / "a")
    generate(make_config(seed=2), tmp_path / "b")
    a, b = tree_hashes(tmp_path / "a"), tree_hashes(tmp_path / "b")
    for name in ("agents.ndjson", "telemetry.ndjson", "cost.ndjson", "persons.ndjson"):
        assert a[name] != b[name], name


def test_epoch_changes_output(tmp_path: Path) -> None:
    generate(make_config(), tmp_path / "a")
    cfg = GenerateConfig(
        seed=1, profile=PROFILES["tiny"], cloud="commercial", epoch="2027-01-01T00:00:00Z"
    )
    generate(cfg, tmp_path / "b")
    assert DEFAULT_EPOCH != cfg.epoch
    assert (
        tree_hashes(tmp_path / "a")["telemetry.ndjson"]
        != tree_hashes(tmp_path / "b")["telemetry.ndjson"]
    )


def test_clouds_never_mixed(tmp_path: Path) -> None:
    generate(make_config(cloud="commercial"), tmp_path / "c")
    generate(make_config(cloud="government"), tmp_path / "g")
    for name in ALL_FILES:
        if name.endswith("run-manifest.json"):
            continue
        commercial = (tmp_path / "c" / name).read_text(encoding="utf-8")
        government = (tmp_path / "g" / name).read_text(encoding="utf-8")
        assert "government" not in commercial, name
        assert "usgov" not in commercial, name
        assert "commercial" not in government, name
        assert "eastus" not in government, name


def test_output_uses_lf_and_ascii(tiny_dir: Path) -> None:
    raw = (tiny_dir / "telemetry.ndjson").read_bytes()
    assert b"\r" not in raw
    assert raw.endswith(b"\n")
    raw.decode("ascii")
