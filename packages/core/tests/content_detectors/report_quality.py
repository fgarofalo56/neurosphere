"""Measure the PRP-101 detectors on the labelled corpus and rewrite the runbook table.

Run manually from the repository root (CI only runs the gate in ``test_corpus_quality.py``)::

    uv run python packages/core/tests/content_detectors/report_quality.py

Prints the generated block and replaces the text between ``<!-- quality-table:start -->`` and
``<!-- quality-table:end -->`` in ``docs/runbooks/content-classification.md``. ``--check``
prints only and exits 1 when the runbook block differs (the date line is ignored).
"""

from __future__ import annotations

import argparse
import datetime as dt
import importlib
import sys
from pathlib import Path
from types import ModuleType

_HERE = Path(__file__).resolve()
RUNBOOK = _HERE.parents[4] / "docs" / "runbooks" / "content-classification.md"


def _corpus_module() -> ModuleType:
    if __package__:
        return importlib.import_module(".corpus", __package__)
    sys.path.insert(0, str(_HERE.parents[1]))  # packages/core/tests: content_detectors package
    return importlib.import_module("content_detectors.corpus")


def _strip_date(block: str) -> str:
    return "\n".join(line for line in block.splitlines() if " measured " not in line)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Rewrite the PRP-101 quality table.")
    parser.add_argument("--check", action="store_true", help="compare only, do not write")
    args = parser.parse_args(argv)
    corpus = _corpus_module()
    report = corpus.measure(corpus.build_corpus(corpus.DEFAULT_SEED), seed=corpus.DEFAULT_SEED)
    block = corpus.render_markdown(report, today=dt.datetime.now(dt.UTC).date())
    print(block)
    text = RUNBOOK.read_text(encoding="utf-8")
    start, end = corpus.TABLE_START, corpus.TABLE_END
    if text.count(start) != 1 or text.count(end) != 1:
        print("runbook markers missing or duplicated", file=sys.stderr)
        return 1
    head, rest = text.split(start, 1)
    current, tail = rest.split(end, 1)
    if args.check:
        return 0 if _strip_date(current.strip()) == _strip_date(block) else 1
    RUNBOOK.write_text(f"{head}{start}\n{block}\n{end}{tail}", encoding="utf-8", newline="\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
