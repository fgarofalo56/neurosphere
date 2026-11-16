"""Render the five Mermaid blocks of docs/ARCHITECTURE.md to docs/diagrams/NN-<name>.svg.

Exit code 1 if the block count is not 5 or any block fails to parse/render (the failing
block is named), 0 on success. Rendering uses a pinned @mermaid-js/mermaid-cli through
`pnpm dlx` (needs Node, pnpm and a headless Chromium that puppeteer can download).

Usage:
    python scripts/render_mermaid.py              # render into docs/diagrams/
    python scripts/render_mermaid.py --source F   # another markdown file (negative proof)
    python scripts/render_mermaid.py --out DIR    # write SVGs elsewhere
    python scripts/render_mermaid.py --no-sandbox # pass the no-sandbox puppeteer config (CI)
    python scripts/render_mermaid.py --source-dir docs/security/dfd --no-sandbox
        # directory mode (PRP-52, #68): render every block of every *.md in the directory,
        # fail on a parse error or on a file with no block; SVGs go to a temp dir unless --out.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "docs" / "ARCHITECTURE.md"
OUT_DIR = ROOT / "docs" / "diagrams"
MERMAID_CLI = "@mermaid-js/mermaid-cli@12.0.0"  # pinned; bump deliberately and re-render
EXPECTED = 5
# Names in ARCHITECTURE.md section order (sections 1 to 5).
NAMES = (
    "component-trust-boundaries",
    "telemetry-projections-live-view",
    "governed-action-sequence",
    "deployment-intelligence",
    "federation-and-dr",
)
BLOCK_RE = re.compile(r"^```mermaid[ \t]*\r?\n(.*?)^```[ \t]*$", re.MULTILINE | re.DOTALL)


def extract_blocks(text: str) -> list[str]:
    """Return the body of every ```mermaid fence, in document order."""
    return [m.group(1) for m in BLOCK_RE.finditer(text)]


def svg_name(index: int) -> str:
    """File name for the 1-based block index."""
    return f"{index:02d}-{NAMES[index - 1]}.svg"


def round_coordinates(svg: str) -> str:
    """Trim path coordinates to 2 decimals.

    mermaid-cli emits 13+ digit floats; the repo PII scan reads a run starting with 4 as a
    card number and rejects the file. Two decimals is sub-pixel and keeps the SVG stable.
    """
    return re.sub(r"(\d+\.\d{2})\d+", r"\1", svg)


def render_block(
    index: int,
    body: str,
    out_dir: Path,
    workdir: Path,
    no_sandbox: bool,
    target_name: str | None = None,
    label: str | None = None,
) -> bool:
    src = workdir / f"block{index}-{target_name or 'arch'}.mmd"
    src.write_text(body, encoding="utf-8")
    target = out_dir / (target_name or svg_name(index))
    cmd = [shutil.which("pnpm") or "pnpm", "dlx", MERMAID_CLI, "-i", str(src), "-o", str(target)]
    if no_sandbox:
        cfg = workdir / "puppeteer.json"
        cfg.write_text(json.dumps({"args": ["--no-sandbox"]}), encoding="utf-8")
        cmd += ["-p", str(cfg)]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False, cwd=workdir)
    if proc.returncode != 0:
        name = label or NAMES[index - 1]
        print(f"FAIL block {index} ({name}): mermaid-cli exit {proc.returncode}")
        print((proc.stderr or proc.stdout).strip())
        return False
    svg = target.read_text(encoding="utf-8")
    target.write_text(round_coordinates(svg), encoding="utf-8")
    print(f"rendered block {index} -> {target.name}")
    return True


def render_directory(source_dir: Path, out_dir: Path, no_sandbox: bool) -> int:
    """Render every mermaid block of every ``*.md`` in ``source_dir``; return an exit code.

    A directory with no markdown file, or a file with no block, fails: a silently empty
    gate is the failure mode this mode exists to prevent.
    """
    files = sorted(source_dir.glob("*.md"))
    if not files:
        print(f"FAIL {source_dir}: no markdown files found")
        return 1
    out_dir.mkdir(parents=True, exist_ok=True)
    failed: list[str] = []
    total = 0
    with tempfile.TemporaryDirectory() as tmp:
        for md in files:
            blocks = extract_blocks(md.read_text(encoding="utf-8"))
            if not blocks:
                print(f"FAIL {md.name}: no mermaid blocks")
                failed.append(md.name)
                continue
            for i, body in enumerate(blocks, start=1):
                total += 1
                name = f"{md.stem}-{i:02d}.svg"
                if not render_block(i, body, out_dir, Path(tmp), no_sandbox, name, name):
                    failed.append(name)
    if failed:
        print(f"FAIL: {len(failed)} item(s) did not render: {failed}")
        return 1
    print(f"PASS: {total} diagrams in {len(files)} files rendered with {MERMAID_CLI}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    ap.add_argument("--source", type=Path, default=SOURCE)
    ap.add_argument("--source-dir", type=Path, default=None)
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--no-sandbox", action="store_true")
    args = ap.parse_args(argv)
    args.source = args.source.resolve()
    if args.source_dir is not None:
        if args.out is not None:
            return render_directory(args.source_dir.resolve(), args.out.resolve(), args.no_sandbox)
        with tempfile.TemporaryDirectory() as tmp_out:
            return render_directory(args.source_dir.resolve(), Path(tmp_out), args.no_sandbox)
    args.out = (args.out or OUT_DIR).resolve()

    blocks = extract_blocks(args.source.read_text(encoding="utf-8"))
    if len(blocks) != EXPECTED:
        print(f"FAIL {args.source.name}: found {len(blocks)} mermaid blocks, expected {EXPECTED}")
        return 1

    args.out.mkdir(parents=True, exist_ok=True)
    failed: list[int] = []
    with tempfile.TemporaryDirectory() as tmp:
        for i, body in enumerate(blocks, start=1):
            if not render_block(i, body, args.out, Path(tmp), args.no_sandbox):
                failed.append(i)
    if failed:
        print(f"FAIL: {len(failed)} block(s) did not render: {failed}")
        return 1
    print(f"PASS: {EXPECTED} diagrams rendered with {MERMAID_CLI}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
