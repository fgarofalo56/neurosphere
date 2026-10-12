"""Portable SIGTERM/SIGINT handling (loop handlers on POSIX, ``signal.signal`` on Windows)."""

from __future__ import annotations

import asyncio
import signal
from collections.abc import Callable
from types import FrameType
from typing import Any

_SIGNALS = (signal.SIGTERM, signal.SIGINT)


def install_signal_handlers(callback: Callable[[], None]) -> Callable[[], None]:
    """Route SIGTERM/SIGINT to ``callback`` on the running loop; return an uninstall function."""
    loop = asyncio.get_running_loop()
    via_loop: list[signal.Signals] = []
    previous: dict[signal.Signals, Any] = {}

    def _threadsafe(_signum: int, _frame: FrameType | None) -> None:
        loop.call_soon_threadsafe(callback)

    for sig in _SIGNALS:
        try:
            loop.add_signal_handler(sig, callback)
            via_loop.append(sig)
        except NotImplementedError:
            # Windows proactor loop: fall back to the classic handler.
            previous[sig] = signal.signal(sig, _threadsafe)

    def uninstall() -> None:
        for sig in via_loop:
            loop.remove_signal_handler(sig)
        for sig, old in previous.items():
            signal.signal(sig, old if old is not None else signal.SIG_DFL)

    return uninstall
