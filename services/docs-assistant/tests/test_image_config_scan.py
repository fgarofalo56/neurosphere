from __future__ import annotations

import re
from pathlib import Path

import pytest
from pydantic import ValidationError

from docs_assistant.config import Settings

SERVICE_DIR = Path(__file__).resolve().parents[1]
SECRETISH = re.compile(r"key|secret|token|passw|credential|connection|conn_str|sas", re.I)
FORBIDDEN_FIELD = re.compile(
    r"product|database|db_|cosmos|password|secret|credential|api_url", re.I
)


def _service_files(suffixes: tuple[str, ...]) -> list[Path]:
    return [
        p
        for p in SERVICE_DIR.rglob("*")
        if p.is_file()
        and p.suffix in suffixes
        and "__pycache__" not in p.parts
        and ".venv" not in p.parts
    ]


def test_config_forbids_extras(tmp_path: Path) -> None:
    assert Settings.model_config.get("extra") == "forbid"
    with pytest.raises(ValidationError):
        Settings(site_dir=tmp_path, product_api_url="https://x.invalid")  # type: ignore[call-arg]


def test_config_has_no_product_database_or_credential_fields() -> None:
    for name in Settings.model_fields:
        assert not FORBIDDEN_FIELD.search(name), name
    # The only key-ish field holds an env var NAME, validated as such.
    with pytest.raises(ValidationError):
        Settings(site_dir=Path("."), model_api_key_env="sk-live-abc123")


def test_dockerfile_has_no_secret_env_or_repo_root_copy() -> None:
    text = (SERVICE_DIR / "Dockerfile").read_text(encoding="utf-8")
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        if stripped.startswith(("ENV ", "ARG ")) or "=" in stripped.split(" ", 1)[0]:
            assert not SECRETISH.search(stripped), stripped
        if stripped.startswith("COPY --from=site "):
            continue  # the named `site` stage, not the build context
        if stripped.startswith("COPY"):
            sources = [t for t in stripped.split()[1:-1] if not t.startswith("--")]
            for src in sources:
                assert src not in {".", "./", "..", "/", "*"}, stripped
                assert not src.startswith(".."), stripped
                assert ".env" not in src, stripped
    assert "USER 10001" in text
    assert "docker-compose" not in text


def test_dockerfile_env_names_scan_covers_all_env_lines() -> None:
    text = (SERVICE_DIR / "Dockerfile").read_text(encoding="utf-8")
    env_block = re.findall(r"^(?:ENV|ARG)\s+([A-Z_]+)=", text, re.M)
    env_block += re.findall(r"^\s+([A-Z_]+)=", text, re.M)
    assert "DOCS_ASSISTANT_SITE_DIR" in env_block
    assert not [n for n in env_block if SECRETISH.search(n)]


def test_service_never_imports_product_packages() -> None:
    pattern = re.compile(
        r"^\s*(?:from|import)\s+neurosphere_(?:api|core|contracts|workers)\b", re.M
    )
    for path in _service_files((".py", ".toml")):
        text = path.read_text(encoding="utf-8")
        if path.name == "pyproject.toml":
            deps = re.search(r"dependencies\s*=\s*\[(.*?)\]", text, re.S)
            assert deps is not None
            assert "neurosphere" not in deps.group(1)
            continue
        if path.name == "test_image_config_scan.py":
            continue
        assert not pattern.search(text), path


def test_no_product_api_url_strings() -> None:
    url = re.compile(r"https?://[^\s\"')]+")
    allowed = ("docs.example.invalid", "x.invalid", "example.invalid")
    for path in _service_files((".py", ".md", ".toml", "")):
        if path.name == "Dockerfile" or path.suffix:
            text = path.read_text(encoding="utf-8", errors="replace")
        else:
            continue
        for found in url.findall(text):
            assert any(a in found for a in allowed) or "docker.com" in found, (path, found)
        assert not re.search(r"/api/v\d", text), path
