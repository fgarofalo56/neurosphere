"""Collect scan outputs, test evidence and configuration baselines into an evidence inventory.

Writes two things, both reproducible byte for byte from unchanged inputs:

* ``docs/evidence/inventory.md`` - committed index (path, sha256, source date, status).
* ``temp/compliance-package/manifest.json`` and ``compliance-package.zip`` - the package.

Determinism: no generation timestamp anywhere, entries sorted by path, LF endings, UTF-8.
The archive uses ZIP_STORED (no compression, so no zlib version dependence), fixed entry
timestamps and permissions and sorted entries, so the archive is byte-identical too.
Text files are hashed and packaged with CRLF normalised to LF so Windows and Linux checkouts
agree. Source date comes from file content (a retrieved/observed/date field) or a
YYYY-MM-DD in the path, else ``undated``. It never comes from mtime or git history.

Safety: paths that look like credentials are filtered BEFORE any file is opened (the regex is
imported from scripts/validate_planning.py). Files whose content looks like a credential are
listed as ``excluded_credential_shaped`` and never copied. Missing expected evidence is listed
as ``missing``; unreadable files are listed as ``failed``. Exit 1 if any row is ``failed``.

NeuroSphere is not FedRAMP authorized; the authorizing official decides.

Usage:
    python scripts/compliance/collect_evidence.py
    python scripts/compliance/collect_evidence.py --root DIR --inventory F --package-dir DIR
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import re
import sys
import zipfile
from dataclasses import dataclass
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]

REPO_ROOT = Path(__file__).resolve().parents[2]
STATEMENT = "not FedRAMP authorized; the authorizing official decides"


def _load_credential_path_re() -> re.Pattern[str]:
    """Import CREDENTIAL_PATH_RE from scripts/validate_planning.py rather than copying it."""
    spec = importlib.util.spec_from_file_location(
        "_ns_validate_planning", REPO_ROOT / "scripts" / "validate_planning.py"
    )
    if spec is None or spec.loader is None:
        raise ImportError("cannot load scripts/validate_planning.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    pattern: re.Pattern[str] = module.CREDENTIAL_PATH_RE
    return pattern


CREDENTIAL_PATH_RE = _load_credential_path_re()
# Extra path shapes that are never collected (secret stores, ssh/aws dirs, VCS internals,
# and any .env* including .env.example).
EXTRA_EXCLUDED_PATH_RE = re.compile(
    r"(^|/)(\.ssh|\.aws|\.git|\.gnupg|node_modules)/|(^|/)id_(rsa|ed25519|ecdsa)|"
    r"(^|/)\.netrc$|(^|/)\.env",
    re.IGNORECASE,
)

# Content shapes that mean "this is a credential". Literals are split so this file itself
# never carries a secret-shaped string.
CONTENT_CREDENTIAL_RES = (
    re.compile("-----BEGIN [A-Z ]*" + "PRIVATE KEY-----"),
    re.compile("Account" + "Key=[A-Za-z0-9+/=]{8,}"),
    re.compile("Shared" + "AccessKey=[A-Za-z0-9+/=]{8,}"),
    re.compile("Default" + "EndpointsProtocol=\\w+;[^\\n]*" + "Account" + "Key="),
    re.compile("[?&]" + "sig" + "=[A-Za-z0-9%+/=]{20,}"),
)

# What the inventory collects (globs relative to the root). Expected patterns are collected too.
COLLECT_GLOBS = (
    "docs/evidence/**/*",
    "docs/compliance/**/*.md",
    "docs/security/**/*.md",
    "docs/ops/*.md",
    "docs/release/*.md",
    "docs/adr/*.md",
    ".github/workflows/*.yml",
    "pyproject.toml",
    "uv.lock",
    "docker-compose.yml",
    "infra/compose/*.json",
    ".gitleaks.toml",
    "SECURITY.md",
)
# Explicit expected evidence. A pattern with no matching file becomes a `missing` row.
EXPECTED = (
    "docs/security/threat-model.md",
    "docs/security/runbooks/incident-response-plan.md",
    "docs/compliance/responsibility-matrix.md",
    "docs/compliance/ssp/*.md",
    "docs/compliance/poam.md",
    "docs/compliance/plans/*.md",
    "docs/evidence/G02/register.yaml",
    "docs/evidence/G07/dr/*.json",
    "docs/evidence/prp-12-supply-chain/*.md",
    "docs/ops/dr-runbook.md",
    "docs/release/dod-checklist.md",
    "docs/adr/0002-stack-pins.md",
    "pyproject.toml",
    "docker-compose.yml",
    "infra/compose/eventhubs.config.json",
    ".gitleaks.toml",
    "SECURITY.md",
)

INVENTORY_REL = "docs/evidence/inventory.md"
DATE_FIELD_RE = re.compile(
    r"""\b(?:retrieved|observed|date)["']?\s*[:=]\s*["']?(\d{4}-\d{2}-\d{2})""",
    re.IGNORECASE,
)
PATH_DATE_RE = re.compile(r"(?<!\d)(\d{4}-\d{2}-\d{2})(?!\d)")
DATE_SCAN_BYTES = 65536
ZIP_EPOCH = (1980, 1, 1, 0, 0, 0)

COLLECTED = "collected"
MISSING = "missing"
EXCLUDED = "excluded_credential_shaped"
FAILED = "failed"


@dataclass(frozen=True)
class Row:
    path: str
    sha256: str
    source_date: str
    status: str
    payload: bytes | None = None  # bytes to package; only set when collected


def is_credential_path(rel: str) -> bool:
    """True when the relative posix path must never be opened or collected."""
    return bool(CREDENTIAL_PATH_RE.search(rel) or EXTRA_EXCLUDED_PATH_RE.search(rel))


def looks_like_credential(data: bytes) -> bool:
    text = data.decode("latin-1")
    return any(rx.search(text) for rx in CONTENT_CREDENTIAL_RES)


def normalise(data: bytes) -> bytes:
    """CRLF to LF for text files; binary content (NUL byte) is left alone."""
    if b"\x00" in data:
        return data
    return data.replace(b"\r\n", b"\n")


def source_date(rel: str, data: bytes) -> str:
    """Date from file content, else from the path, else 'undated'. Never mtime or git."""
    head = data[:DATE_SCAN_BYTES].decode("utf-8", errors="ignore")
    m = DATE_FIELD_RE.search(head) or PATH_DATE_RE.search(rel)
    return m.group(1) if m else "undated"


def _glob_files(root: Path, pattern: str) -> list[str]:
    out: list[str] = []
    for p in root.glob(pattern):
        if p.is_symlink() or p.is_file():
            out.append(p.relative_to(root).as_posix())
    return out


def _collect_one(root: Path, rel: str) -> Row:
    # Path filter first: a credential-shaped file is never opened.
    if is_credential_path(rel):
        return Row(rel, "-", "-", EXCLUDED)
    full = root / rel
    if full.is_symlink():
        return Row(rel, "-", "-", f"{FAILED}: symlink not followed")
    try:
        data = normalise(full.read_bytes())
    except OSError as exc:
        return Row(rel, "-", "-", f"{FAILED}: {type(exc).__name__}")
    if looks_like_credential(data):
        return Row(rel, "-", "-", EXCLUDED)
    return Row(
        rel, hashlib.sha256(data).hexdigest(), source_date(rel, data), COLLECTED, payload=data
    )


def collect(root: Path, inventory_rel: str = INVENTORY_REL) -> list[Row]:
    """Return one sorted row per collected, excluded, failed or missing item."""
    paths: set[str] = set()
    for pattern in (*COLLECT_GLOBS, *EXPECTED):
        paths.update(_glob_files(root, pattern))
    paths.discard(inventory_rel)  # the index does not index itself
    rows = [_collect_one(root, rel) for rel in paths]
    for pattern in EXPECTED:
        matches = [r for r in _glob_files(root, pattern) if not is_credential_path(r)]
        if not matches:
            rows.append(Row(pattern, "-", "-", MISSING))
    return sorted(rows, key=lambda r: (r.path, r.status))


def render_inventory(rows: list[Row]) -> str:
    counts: dict[str, int] = {}
    for r in rows:
        key = r.status.split(":", 1)[0]
        counts[key] = counts.get(key, 0) + 1
    summary = ", ".join(f"{k} {counts[k]}" for k in sorted(counts)) or "no rows"
    lines = [
        "# Evidence inventory",
        "",
        f"Status: evidence aid, not an assessment. NeuroSphere is {STATEMENT}. No certification "
        "or authorization date is promised.",
        "",
        "Generated by `scripts/compliance/collect_evidence.py`; do not edit by hand. The file has "
        "no generation timestamp, so reruns on unchanged inputs are byte-identical. `sha256` is "
        "over the file content with CRLF normalised to LF. `source date` is read from file "
        "content (a retrieved, observed or date field) or from a YYYY-MM-DD in the path, else "
        "`undated`; it is never file mtime or git history.",
        "",
        "Status vocabulary: `collected`; `missing` (expected evidence not present, the path "
        "column shows the expected pattern); `excluded_credential_shaped` (path or content "
        "looks like a credential, never copied into the package); `failed: <reason>` (could "
        "not be read).",
        "",
        f"Rows: {len(rows)} ({summary}). The package archive and manifest are written to "
        "`temp/compliance-package/` (gitignored) and are not committed.",
        "",
        "| path | sha256 | source date | status |",
        "|---|---|---|---|",
    ]
    for r in rows:
        path = r.path.replace("|", "\\|")
        lines.append(f"| `{path}` | {r.sha256} | {r.source_date} | {r.status} |")
    return "\n".join(lines) + "\n"


def render_manifest(rows: list[Row]) -> str:
    entries = [
        {"path": r.path, "sha256": r.sha256, "source_date": r.source_date, "status": r.status}
        for r in rows
    ]
    doc = {"statement": f"NeuroSphere is {STATEMENT}", "entries": entries}
    return json.dumps(doc, indent=2, sort_keys=True, ensure_ascii=True) + "\n"


def _zip_info(name: str) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name, date_time=ZIP_EPOCH)
    info.compress_type = zipfile.ZIP_STORED
    info.external_attr = 0o644 << 16
    info.create_system = 3
    return info


def write_package(rows: list[Row], manifest: str, package_dir: Path) -> Path:
    package_dir.mkdir(parents=True, exist_ok=True)
    (package_dir / "manifest.json").write_bytes(manifest.encode("utf-8"))
    archive = package_dir / "compliance-package.zip"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_STORED) as zf:
        zf.writestr(_zip_info("manifest.json"), manifest.encode("utf-8"))
        for r in rows:  # rows are already sorted by path
            if r.status == COLLECTED and r.payload is not None:
                zf.writestr(_zip_info(f"files/{r.path}"), r.payload)
    return archive


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Build the NeuroSphere evidence inventory.")
    ap.add_argument("--root", type=Path, default=REPO_ROOT, help="repository root to scan")
    ap.add_argument("--inventory", type=Path, default=None, help="inventory.md output path")
    ap.add_argument("--package-dir", type=Path, default=None, help="package output directory")
    args = ap.parse_args(argv)
    root: Path = args.root.resolve()
    inventory: Path = args.inventory or root / INVENTORY_REL
    package_dir: Path = args.package_dir or root / "temp" / "compliance-package"
    try:
        inv_rel = inventory.resolve().relative_to(root).as_posix()
    except ValueError:
        inv_rel = INVENTORY_REL

    rows = collect(root, inv_rel)
    inventory.parent.mkdir(parents=True, exist_ok=True)
    inventory.write_bytes(render_inventory(rows).encode("utf-8"))
    write_package(rows, render_manifest(rows), package_dir)

    failed = [r for r in rows if r.status.startswith(FAILED)]
    missing = [r for r in rows if r.status == MISSING]
    excluded = [r for r in rows if r.status == EXCLUDED]
    print(f"inventory: {len(rows)} rows -> {inventory}")
    print(f"package: {package_dir}")
    print(
        f"missing: {len(missing)}, excluded_credential_shaped: {len(excluded)}, "
        f"failed: {len(failed)}"
    )
    for r in failed:
        print(f"  FAILED {r.path}: {r.status}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
