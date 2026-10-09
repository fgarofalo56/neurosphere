"""Render the five Mermaid blocks of docs/ARCHITECTURE.md to docs/diagrams/NN-<name>.svg.

Exit code 1 if the block count is not 5 or any block fails to parse/render (the failing
block is named), 0 on success. Rendering uses a pinned @mermaid-js/mermaid-cli through
`pnpm dlx` (needs Node, pnpm and a headless Chromium that puppeteer can download).

Usage:
    python scripts/render_mermaid.py              # render into docs/diagrams/
    python scripts/render_mermaid.py --source F   # another markdown file (negative proof)
    python scripts/render_mermaid.py --out DIR    # write SVGs elsewhere
    python scripts/render_mermaid.py --no-sandbox # pass the no-sandbox puppeteer config (CI)
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


def render_block(index: int, body: str, out_dir: Path, workdir: Path, no_sandbox: bool) -> bool:
    src = workdir / f"block{index}.mmd"
    src.write_text(body, encoding="utf-8")
    target = out_dir / svg_name(index)
    cmd = [shutil.which("pnpm") or "pnpm", "dlx", MERMAID_CLI, "-i", str(src), "-o", str(target)]
    if no_sandbox:
        cfg = workdir / "puppeteer.json"
        cfg.write_text(json.dumps({"args": ["--no-sandbox"]}), encoding="utf-8")
        cmd += ["-p", str(cfg)]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False, cwd=workdir)
    if proc.returncode != 0:
        print(f"FAIL block {index} ({NAMES[index - 1]}): mermaid-cli exit {proc.returncode}")
        print((proc.stderr or proc.stdout).strip())
        return False
    print(f"rendered block {index} -> {target.name}")
    return True


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    ap.add_argument("--source", type=Path, default=SOURCE)
    ap.add_argument("--out", type=Path, default=OUT_DIR)
    ap.add_argument("--no-sandbox", action="store_true")
    args = ap.parse_args(argv)
    args.source = args.source.resolve()
    args.out = args.out.resolve()

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
