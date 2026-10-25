"""Write (or check) the container export: ``python -m neurosphere_core.stores [--check] [PATH]``.

``PATH`` defaults to ``infra/compose/cosmos-containers.json`` relative to the current directory
(run from the repository root). ``--check`` exits 1 when the file differs from the registry and
writes nothing; the drift test in ``packages/core/tests/stores_registry`` does the same in CI.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Final

from neurosphere_core.stores.containers import export_json

DEFAULT_EXPORT_PATH: Final = Path("infra/compose/cosmos-containers.json")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m neurosphere_core.stores")
    parser.add_argument("path", nargs="?", type=Path, default=DEFAULT_EXPORT_PATH)
    parser.add_argument("--check", action="store_true", help="fail on drift, write nothing")
    args = parser.parse_args(argv)
    path: Path = args.path
    expected = export_json()
    if args.check:
        current = path.read_text(encoding="utf-8") if path.exists() else None
        if current != expected:
            print(f"{path}: out of date; run python -m neurosphere_core.stores", file=sys.stderr)
            return 1
        print(f"{path}: up to date")
        return 0
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(expected, encoding="utf-8", newline="\n")
    print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
