"""G01 scripts: a CLI-supplied --evidence-dir must resolve inside the evidence root (#101).

Offline: NS_LIVE_APPROVED is set only so the path check (which runs before any connection or az
call) is reached; every case is refused before a runner or az command could start.
"""

from __future__ import annotations

import importlib.util
import sys
import uuid
from pathlib import Path
from types import ModuleType

import pytest

GATES = Path(__file__).resolve().parents[3] / "scripts" / "gates"
SUB = "11111111-2222-3333-4444-555555555555"


def _load(script: str) -> ModuleType:
    name = f"{script}_confine_{uuid.uuid4().hex[:6]}"
    spec = importlib.util.spec_from_file_location(name, GATES / f"{script}.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def _run(script: str, evidence_dir: str, root: Path) -> int:
    mod = _load(script)
    if script == "g01_analytics_live":
        return int(
            mod.main(
                ["--adapter", "fabric", "--evidence-dir", evidence_dir],
                runners={"fabric": _boom},
                evidence_roots=[root],
            )
        )
    argv = [
        "--subscription",
        SUB,
        "--resource-group",
        "rg-ns-g01-test",
        "--apim-publisher-email",
        "ops@example.invalid",
        "--apim-publisher-name",
        "Ops",
        "--evidence-dir",
        evidence_dir,
    ]
    return int(mod.main(argv, runner=_boom, work_dir=root / "work", evidence_roots=[root]))


async def _boom(*_a: object, **_k: object) -> None:
    raise AssertionError("runner must not start when the evidence dir is refused")


@pytest.fixture(autouse=True)
def _approved(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NS_LIVE_APPROVED", "1")


SCRIPTS = ["g01_analytics_live", "g01_deploy_smoke"]


@pytest.mark.parametrize("script", SCRIPTS)
def test_traversal_is_refused_and_nothing_written(
    script: str, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / "root"
    root.mkdir()
    escape = str(root / ".." / "escape")
    assert _run(script, escape, root) == 2
    assert "evidence-dir" in capsys.readouterr().err
    assert not (tmp_path / "escape").exists()
    assert list(root.iterdir()) == []


@pytest.mark.parametrize("script", SCRIPTS)
def test_absolute_out_of_root_is_refused_and_nothing_written(
    script: str, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / "root"
    root.mkdir()
    outside = tmp_path / "outside"
    assert _run(script, str(outside), root) == 2
    assert "evidence-dir" in capsys.readouterr().err
    assert not outside.exists()
    assert list(root.iterdir()) == []


@pytest.mark.parametrize("script", SCRIPTS)
def test_default_root_refuses_tmp_path_without_override(script: str, tmp_path: Path) -> None:
    mod = _load(script)
    root_name = "EVIDENCE_DIR" if script == "g01_analytics_live" else "EVIDENCE_ROOT"
    default_root = getattr(mod, root_name)
    with pytest.raises(mod.RefusedError):
        mod.confine_evidence_dir(str(tmp_path / "ev"), [default_root])
    assert (
        mod.confine_evidence_dir(str(default_root / "sub"), [default_root])
        == (default_root / "sub").resolve()
    )
