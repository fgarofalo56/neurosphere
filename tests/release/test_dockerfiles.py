"""Static checks on the production Dockerfiles and .dockerignore (no docker needed)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
DOCKERFILES = {
    "api": ROOT / "services" / "api" / "Dockerfile",
    "workers": ROOT / "services" / "workers" / "Dockerfile",
    "frontend": ROOT / "frontend" / "Dockerfile",
}
DIGEST = re.compile(r"@sha256:[0-9a-f]{64}$")


def _instructions(path: Path) -> list[tuple[str, str]]:
    """Return (INSTRUCTION, arguments) pairs with continuations joined and comments dropped."""
    out: list[tuple[str, str]] = []
    buf = ""
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not buf and (not line or line.startswith("#")):
            continue
        if line.endswith("\\"):
            buf += line[:-1] + " "
            continue
        buf += line
        head, _, rest = buf.partition(" ")
        out.append((head.upper(), rest.strip()))
        buf = ""
    return out


def _from_images(path: Path) -> list[str]:
    images = []
    for name, args in _instructions(path):
        if name == "FROM":
            tokens = [t for t in args.split() if not t.startswith("--")]
            images.append(tokens[0])
    return images


def _copy_from_images(path: Path) -> list[str]:
    images = []
    for name, args in _instructions(path):
        if name != "COPY":
            continue
        for token in args.split():
            if token.startswith("--from="):
                images.append(token.removeprefix("--from="))
    return images


@pytest.mark.parametrize("name", sorted(DOCKERFILES))
def test_final_stage_user_is_numeric_non_root(name: str) -> None:
    users = [args for ins, args in _instructions(DOCKERFILES[name]) if ins == "USER"]
    assert users, "no USER directive"
    final = users[-1].split(":")[0]
    assert final.isdigit(), f"final USER must be numeric, got {final!r}"
    assert int(final) != 0
    # The last USER must come after the last FROM (i.e. be in the final stage).
    instr = [ins for ins, _ in _instructions(DOCKERFILES[name])]
    last_from = max(i for i, ins in enumerate(instr) if ins == "FROM")
    last_user = max(i for i, ins in enumerate(instr) if ins == "USER")
    assert last_user > last_from


@pytest.mark.parametrize("name", sorted(DOCKERFILES))
def test_every_image_is_pinned_by_digest(name: str) -> None:
    path = DOCKERFILES[name]
    stage_names = {
        args.split()[-1]
        for ins, args in _instructions(path)
        if ins == "FROM" and " AS " in args.upper()
    }
    images = [i for i in _from_images(path) if i not in stage_names] + [
        i for i in _copy_from_images(path) if i not in stage_names
    ]
    assert images, "no base images found"
    for image in images:
        assert DIGEST.search(image), f"{image} is not pinned by @sha256 digest"


@pytest.mark.parametrize("name", sorted(DOCKERFILES))
def test_multi_stage(name: str) -> None:
    assert len(_from_images(DOCKERFILES[name])) >= 2


@pytest.mark.parametrize("name", sorted(DOCKERFILES))
def test_no_latest_remote_add_or_env_copy(name: str) -> None:
    path = DOCKERFILES[name]
    text = path.read_text(encoding="utf-8")
    assert ":latest" not in text
    for ins, args in _instructions(path):
        if ins == "ADD":
            sources = [t for t in args.split() if not t.startswith("--")][:-1]
            assert not any(re.match(r"https?://", s) for s in sources), "ADD of a remote URL"
        if ins in {"COPY", "ADD"}:
            tokens = [t for t in args.split() if not t.startswith("--")]
            assert not any(Path(t).name.startswith(".env") for t in tokens), "copies a .env file"


@pytest.mark.parametrize("name", ["api", "workers"])
def test_python_images_default_to_non_local_env(name: str) -> None:
    text = DOCKERFILES[name].read_text(encoding="utf-8")
    assert re.search(r"NS_ENV=(prod|staging|dev|test)\b", text)
    assert "NS_ENV=local" not in text


def _dockerignore_lines() -> list[str]:
    lines = (ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()
    return [ln.strip() for ln in lines if ln.strip() and not ln.strip().startswith("#")]


@pytest.mark.parametrize(
    "pattern",
    [".env", ".env.*", ".git", "temp", "docs", "PRPs", ".claude", "**/node_modules", "**/tests"],
)
def test_dockerignore_has_required_exclusions(pattern: str) -> None:
    assert pattern in _dockerignore_lines()


def test_dockerignore_does_not_exclude_build_inputs_or_secrets_exception() -> None:
    lines = _dockerignore_lines()
    for needed in ("frontend", "packages", "services"):
        assert needed not in lines
        assert f"{needed}/" not in lines
    assert not [ln for ln in lines if ln.startswith("!")], "negation patterns are not allowed"
