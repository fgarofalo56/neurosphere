"""PRP-21 round 2 item 1: the admission builder is opt-in and never unlimited."""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest
from neurosphere_api.runtime.builders import admission as admission_builder
from neurosphere_api.runtime.builders import default_builders
from neurosphere_core.admission import DEFAULT_LIMIT, TokenBucketLimiter
from runtime_api.runtime_helpers import Composed, compose  # pyright: ignore[reportMissingImports]


def _compose() -> Composed:
    return compose(builders=(admission_builder.BUILDER,))


def test_registered_in_default_builders() -> None:
    assert admission_builder.BUILDER in default_builders()


def test_off_by_default() -> None:
    assert not hasattr(_compose().app.state, "admission")


def test_enabled_without_file_uses_default_and_warns(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setenv("NS_ADMISSION_ENABLED", "true")
    with caplog.at_level(logging.WARNING):
        composed = _compose()
    limiter = composed.app.state.admission
    assert isinstance(limiter, TokenBucketLimiter)
    assert limiter.limit_for(_any_key()) == DEFAULT_LIMIT
    assert "default quota applies" in caplog.text


def test_enabled_with_policy_file(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    path = tmp_path / "q.json"
    path.write_text(json.dumps({"default": {"rate_per_second": 2, "burst": 4}}), encoding="utf-8")
    monkeypatch.setenv("NS_ADMISSION_ENABLED", "true")
    monkeypatch.setenv("NS_ADMISSION_POLICY_FILE", str(path))
    limiter = _compose().app.state.admission
    assert limiter.limit_for(_any_key()).burst == 4


def test_unreadable_file_falls_back_to_default_never_unlimited(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("NS_ADMISSION_ENABLED", "true")
    monkeypatch.setenv("NS_ADMISSION_POLICY_FILE", str(tmp_path / "missing.json"))
    limiter = _compose().app.state.admission
    assert limiter.limit_for(_any_key()) == DEFAULT_LIMIT


def test_invalid_setting_enables_admission(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NS_ADMISSION_ENABLED", "maybe")
    assert isinstance(_compose().app.state.admission, TokenBucketLimiter)


def _any_key():
    from neurosphere_core.admission import LimiterKey

    return LimiterKey("commercial", "c", None, "h")
