"""Put the repo root on sys.path so the PRP-71 ``sandbox`` package resolves (not installed)."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = str(Path(__file__).resolve().parents[3])
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
