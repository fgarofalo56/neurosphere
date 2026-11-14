"""Offline billing-vs-ledger variance report (PRP-09 round 2 item 12).

Reads a LOCAL Cost Management export (one CSV or CSV.gz file, or a directory of them) and a
LOCAL JSON file of ledger ESTIMATES, runs ``build_variance_report`` and prints the JSON report
(granularity statement included). No network, no Azure calls, no credentials.

Estimates file: a JSON list of ``{"usage_date": "YYYY-MM-DD", "resource_id": str|null,
"currency": "USD"|null, "amount": "1.50"|null}``. A null amount is unknown, never 0.

Every path is resolved and must stay inside ``--input-dir``; a ``..`` escape, an absolute path
outside it, or a symlink pointing out of it is refused (exit 2).

Exit codes: 0 report printed, 2 refused or unreadable input.
"""

from __future__ import annotations

import argparse
import gzip
import io
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Final

from neurosphere_connector_azure_billing import (
    CostRow,
    LedgerEstimate,
    aggregate_daily,
    build_variance_report,
    parse_cost_csv,
)
from neurosphere_connector_azure_billing.export_reader import MAX_DECOMPRESSED_BYTES
from pydantic import ValidationError

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")  # pyright: ignore[reportAttributeAccessIssue]

__all__ = ["RefusedError", "confine", "main", "run"]

_MAX_FILE_BYTES: Final = 64 * 1024 * 1024
_MAX_FILES: Final = 1000


class RefusedError(Exception):
    """An input was refused (path escape, too large, unreadable, malformed)."""


def confine(root: Path, raw: str) -> Path:
    """Resolve ``raw`` (relative to ``root`` unless absolute) and require it inside ``root``."""
    base = root.resolve()
    resolved = (base / raw).resolve()
    if not resolved.is_relative_to(base):
        raise RefusedError("path resolves outside --input-dir")
    return resolved


def _read_bytes(path: Path, base: Path) -> bytes:
    resolved = path.resolve()
    if not resolved.is_relative_to(base):
        raise RefusedError("path resolves outside --input-dir")
    if not resolved.is_file():
        raise RefusedError("not a file")
    if resolved.stat().st_size > _MAX_FILE_BYTES:
        raise RefusedError("input file too large")
    return resolved.read_bytes()


def _export_files(target: Path, base: Path) -> list[Path]:
    if target.is_file():
        return [target]
    if not target.is_dir():
        raise RefusedError("export path does not exist")
    files = sorted(
        p for p in target.rglob("*") if p.is_file() and p.name.lower().endswith((".csv", ".csv.gz"))
    )
    if len(files) > _MAX_FILES:
        raise RefusedError("too many export files")
    return [p for p in files if p.resolve().is_relative_to(base)]


def _csv_text(path: Path, base: Path) -> str:
    data = _read_bytes(path, base)
    if path.name.lower().endswith(".gz"):
        try:
            with gzip.GzipFile(fileobj=io.BytesIO(data)) as handle:
                data = handle.read(MAX_DECOMPRESSED_BYTES + 1)
        except (OSError, EOFError):
            raise RefusedError("export file is not valid gzip") from None
        if len(data) > MAX_DECOMPRESSED_BYTES:
            raise RefusedError("export file exceeds the decompressed size cap")
    return data.decode("utf-8-sig")


def run(
    input_dir: Path,
    export: str,
    estimates: str,
    *,
    basis: str = "actual",
    level: str = "day_resource",
    amount_kind: str = "estimated",
) -> dict[str, Any]:
    base = input_dir.resolve()
    if not base.is_dir():
        raise RefusedError("--input-dir is not a directory")
    if basis not in ("actual", "amortized") or level not in ("day", "day_resource"):
        raise RefusedError("unsupported --basis or --level")
    if amount_kind not in ("estimated", "invoiced"):
        raise RefusedError("unsupported --amount-kind")
    export_path = confine(base, export)
    estimates_path = confine(base, estimates)

    rows: list[CostRow] = []
    for file in _export_files(export_path, base):
        rows.extend(
            parse_cost_csv(
                _csv_text(file, base),
                basis=basis,  # type: ignore[arg-type]
                amount_kind=amount_kind,  # type: ignore[arg-type]
            )
        )
    without_date = sum(1 for r in rows if r.usage_date is None)

    try:
        raw: Any = json.loads(_read_bytes(estimates_path, base))
        if not isinstance(raw, list):
            raise RefusedError("estimates file must be a JSON list")
        items: list[Any] = raw  # pyright: ignore[reportUnknownVariableType]
        ledger = [LedgerEstimate.model_validate(item) for item in items]
    except (ValueError, ValidationError):
        raise RefusedError("estimates file is not valid") from None

    report = build_variance_report(
        aggregate_daily(rows),
        ledger,
        level=level,  # type: ignore[arg-type]
        basis=basis,  # type: ignore[arg-type]
        rows_without_date=without_date,
    )
    return report.model_dump(mode="json")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0] if __doc__ else None)
    parser.add_argument("--input-dir", required=True, type=Path)
    parser.add_argument("--export", required=True, help="CSV/CSV.gz file or directory in input-dir")
    parser.add_argument("--estimates", required=True, help="estimates JSON file in input-dir")
    parser.add_argument("--basis", default="actual", choices=("actual", "amortized"))
    parser.add_argument("--level", default="day_resource", choices=("day", "day_resource"))
    parser.add_argument(
        "--amount-kind",
        default="estimated",
        choices=("estimated", "invoiced"),
        help="what the export holds (the file does not say); it labels every billing line",
    )
    args = parser.parse_args(argv)
    try:
        report = run(
            args.input_dir,
            args.export,
            args.estimates,
            basis=args.basis,
            level=args.level,
            amount_kind=args.amount_kind,
        )
    except RefusedError as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
