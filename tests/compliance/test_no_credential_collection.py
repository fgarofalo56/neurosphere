"""Credential-shaped paths and content are never collected into the package.

Fixtures are built at test time. Credential-shaped literals are split so no committed line
matches a secret scanner.
"""

from __future__ import annotations

import zipfile
from pathlib import Path
from types import ModuleType

CRED_CONTENT = {
    "docs/evidence/leak-key.md": "-----BEGIN " + "PRIVATE KEY-----\nabc\n",
    "docs/evidence/leak-conn.md": "Account" + "Key=" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4==\n",
    "docs/evidence/leak-sas.md": "https://x.example/blob?sv=1&" + "sig" + "=" + "A" * 30 + "\n",
}
CRED_PATHS = (
    "docs/evidence/.env",
    "docs/evidence/.env.local",
    "docs/evidence/.env.example",
    "docs/evidence/secrets/x.txt",
    "docs/evidence/foo.pem",
    "docs/evidence/credentials.json",
    "docs/evidence/.ssh/id_rsa",
)
SENTINEL = "SENTINEL-PLANTED-VALUE"


def _build(root: Path) -> None:
    ev = root / "docs" / "evidence"
    ev.mkdir(parents=True)
    (ev / "ok.md").write_text("fine\n", encoding="utf-8")
    for rel in CRED_PATHS:
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(SENTINEL, encoding="utf-8")
    for rel, body in CRED_CONTENT.items():
        (root / rel).write_text(body + SENTINEL, encoding="utf-8")


def _run(collector: ModuleType, root: Path, tmp_path: Path) -> tuple[str, Path]:
    pkg = tmp_path / "pkg"
    inv = tmp_path / "inv.md"
    rc = collector.main(["--root", str(root), "--inventory", str(inv), "--package-dir", str(pkg)])
    assert rc == 0
    return inv.read_text(encoding="utf-8"), pkg


def test_credential_shaped_paths_and_content_are_not_packaged(
    collector: ModuleType, tmp_path: Path
) -> None:
    root = tmp_path / "repo"
    _build(root)
    inventory, pkg = _run(collector, root, tmp_path)

    with zipfile.ZipFile(pkg / "compliance-package.zip") as zf:
        names = zf.namelist()
        blobs = b"".join(zf.read(n) for n in names)
    assert "files/docs/evidence/ok.md" in names
    assert SENTINEL.encode() not in blobs
    assert SENTINEL.encode() not in (pkg / "manifest.json").read_bytes()
    for rel in (*CRED_PATHS, *CRED_CONTENT):
        assert f"files/{rel}" not in names

    rows = {ln.split("`")[1]: ln for ln in inventory.splitlines() if ln.startswith("| `")}
    for rel in (*CRED_PATHS, *CRED_CONTENT):
        assert rows[rel].endswith("| excluded_credential_shaped |"), rel
        assert "| - | - |" in rows[rel], rel


def test_credential_path_is_never_opened(
    collector: ModuleType, tmp_path: Path, monkeypatch
) -> None:
    root = tmp_path / "repo"
    _build(root)
    opened: list[str] = []
    real = Path.read_bytes

    def spy(self: Path) -> bytes:
        opened.append(self.as_posix())
        return real(self)

    monkeypatch.setattr(Path, "read_bytes", spy)
    collector.collect(root)
    for rel in CRED_PATHS:
        assert not any(o.endswith(rel) for o in opened), rel


def test_collector_reuses_validate_planning_regex(collector: ModuleType) -> None:
    assert collector.is_credential_path("a/.env")
    assert collector.is_credential_path("a/secrets/b")
    assert collector.is_credential_path("x/credentials.json")
    assert not collector.is_credential_path("docs/evidence/ok.md")
