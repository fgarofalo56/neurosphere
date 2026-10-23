"""Restore drill on the compose emulators (PRP-21 item 5).

Run ``docker compose up -d --wait`` first. If the emulators are unreachable this FAILS: a
drill that was never run is an open gate, not a skipped green test.
"""

from __future__ import annotations

import socket

import ns_dr_drill as drill  # pyright: ignore[reportMissingImports]
import ns_dr_emulator  # pyright: ignore[reportMissingImports]
import pytest

pytestmark = pytest.mark.integration

EMULATOR_PORTS = {"cosmos": 8081, "azurite-blob": 10000}


def _require_emulators() -> None:
    down = []
    for name, port in EMULATOR_PORTS.items():
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=3):
                pass
        except OSError:
            down.append(f"{name} (127.0.0.1:{port})")
    if down:
        pytest.fail(f"compose emulators unreachable, run `docker compose up -d --wait`: {down}")


async def test_restore_drill_restores_every_store() -> None:
    _require_emulators()
    result = await drill.run_drill(ns_dr_emulator.load_connections({}))

    names = {s.store for s in result.stores}
    assert names == {
        "cosmos:cost-ledger",
        "cosmos:outbox",
        "cosmos:catalog",
        "cosmos:aggregates",
        "blob:archive",
        "blob:quarantine",
        "blob:checkpoints",
        "search:index",
    }
    for s in result.stores:
        assert s.source_count > 0, s.store
        assert s.restored_count == s.source_count, s.store
        assert s.restored_sha256 == s.source_sha256, s.store
        assert s.match, s.store
        assert s.restore_seconds >= 0.0
    assert result.all_match
    # Writes made after the backup are gone, and the checkpoint is rewound to the snapshot.
    assert result.post_backup_writes_lost > 0
    assert result.post_backup_writes_absent_after_restore
    assert result.checkpoint_rewound
    assert result.recovery_point_gap_seconds > 0.0
