"""Runtime wiring: idle without storage, targets from real backends, mode and policy settings."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, cast

import pytest
from neurosphere_core.audit import AuditRepository, InMemoryAuditStore
from neurosphere_core.clients import ClientLifetime
from neurosphere_core.lifecycle.jobs import InMemoryJobStore
from neurosphere_core.lifecycle.memory import (
    InMemoryHoldRegistry,
    InMemoryMappingStore,
    InMemoryRequestQueue,
)
from neurosphere_core.lifecycle.settings import LifecycleSettings
from neurosphere_workers.lifecycle.assembly import LifecycleParts, assemble, build_targets
from neurosphere_workers.runtime.adapters import IdleRole
from neurosphere_workers.runtime.factories import (
    RuntimeConfig,
    _lifecycle_storage_configured,  # pyright: ignore[reportPrivateUsage]
    build_lifecycle,
)

POLICY = {
    "policy_version": "records-2026-1",
    "retain_prompt_response_bodies": False,
    "rules": [{"data_class": "telemetry", "min_retention_days": 1, "max_retention_days": 30}],
}


def _parts(targets: Any = None) -> LifecycleParts:
    return LifecycleParts(
        jobs=InMemoryJobStore(),
        holds=InMemoryHoldRegistry(),
        queue=InMemoryRequestQueue(),
        mappings=InMemoryMappingStore(),
        audit=AuditRepository(InMemoryAuditStore()),
        targets=targets
        if targets is not None
        else build_targets(cloud="commercial", customer_id="c"),
    )


async def test_without_storage_the_role_is_idle_with_a_reason(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.WARNING):
        role = await build_lifecycle(cast(RuntimeConfig, None), ClientLifetime())
    assert isinstance(role, IdleRole)
    assert role.idle_reason == "lifecycle_no_job_source"
    assert _lifecycle_storage_configured(None) is False


def test_settings_default_to_dry_run_and_reject_a_typo(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("NS_LIFECYCLE_MODE", raising=False)
    assert LifecycleSettings().mode == "dry_run"
    assert LifecycleSettings().max_attempts == 5
    assert LifecycleSettings().policy_file is None
    monkeypatch.setenv("NS_LIFECYCLE_MODE", "execute")
    assert LifecycleSettings().mode == "execute"
    for bad in ("Execute", "yes", "true", "run", ""):
        monkeypatch.setenv("NS_LIFECYCLE_MODE", bad)
        with pytest.raises(ValueError):
            LifecycleSettings()


def test_mode_policy_and_attempts_reach_the_engine(tmp_path: Path) -> None:
    path = tmp_path / "policy.json"
    path.write_text(json.dumps(POLICY), encoding="utf-8")
    settings = LifecycleSettings(mode="execute", policy_file=path, max_attempts=3)
    engine, _ = assemble(_parts(), settings, customer_id="c", cloud="commercial")
    assert engine.mode == "execute"
    assert engine.max_attempts == 3
    assert engine.policy.status == "set"


def test_default_settings_assemble_a_dry_run_engine_with_no_policy() -> None:
    engine, _ = assemble(_parts(), LifecycleSettings(), customer_id="c", cloud="commercial")
    assert engine.mode == "dry_run"
    assert engine.policy.status == "unset"
    assert engine.policy.problem == "not_configured"


def test_an_invalid_policy_file_fails_closed_to_unset(tmp_path: Path) -> None:
    path = tmp_path / "policy.json"
    path.write_text(json.dumps({**POLICY, "rules": []}), encoding="utf-8")
    engine, _ = assemble(
        _parts(), LifecycleSettings(policy_file=path), customer_id="c", cloud="commercial"
    )
    assert (engine.policy.status, engine.policy.problem) == ("unset", "invalid")


def test_assembly_logs_the_mode_at_startup(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING, logger="neurosphere.workers.lifecycle"):
        assemble(_parts(), LifecycleSettings(), customer_id="c", cloud="commercial")
    events = [r for r in caplog.records if r.__dict__.get("event") == "worker.lifecycle_mode"]
    assert len(events) == 1
    assert events[0].__dict__["mode"] == "dry_run"


def test_targets_are_registered_only_for_stores_that_exist() -> None:
    empty = build_targets(cloud="commercial", customer_id="c")
    assert empty.targets() == []
    both = build_targets(
        cloud="commercial", customer_id="c", catalog_container=object(), ledger_container=object()
    )
    assert sorted((t.target_kind, t.container) for t in both.targets()) == [
        ("catalog", "catalog"),
        ("ledger", "cost-ledger"),
    ]
    assert both.get("archive", "archive") is None  # absent store: fails closed as unknown_target


def test_the_audit_container_can_never_be_a_target() -> None:
    with pytest.raises(ValueError):
        build_targets(
            cloud="commercial", customer_id="c", catalog_container=object(), catalog_name="audit"
        )
    with pytest.raises(ValueError):
        build_targets(
            cloud="commercial",
            customer_id="c",
            ledger_container=object(),
            ledger_name="audit_tail",
        )
