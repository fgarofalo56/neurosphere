"""Builders for the PRP-103 item 2 capture tests.

No secret-shaped literal lives here: every canary and every credential-shaped value is
assembled at runtime from fragments and fresh randomness (gitleaks fingerprints literals).
"""

from __future__ import annotations

import secrets
import string
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest
from neurosphere_core.classification import DEFAULT_SET_VERSION
from neurosphere_core.crypto import LocalFileKeyWrapper
from neurosphere_core.interactions import (
    CaptureAuditEvent,
    CaptureEvent,
    CapturePipeline,
    CaptureTarget,
    InMemoryInteractionStore,
)
from neurosphere_core.lifecycle.policy import PolicyState, load_policy

CUSTOMER = "acme"
DOMAIN = "commercial:acme:neurosphere:domain:support"
SOURCE = "otel-gateway"
KEK_URI = "https://acme-kv.vault.azure.net/keys/ns-content-kek"

_ALNUM = string.ascii_letters + string.digits
_UPPER_DIGITS = string.ascii_uppercase + string.digits


def canary() -> str:
    """A fresh canary the detectors leave alone (so a test can see it survive capture).

    ``NSCANARY-<uuid4>`` is not usable here: the dashed GUID is itself detected
    (``opaque_secret`` / ``guid``) and replaced, which would hide whether text was kept.
    """
    return "NSCANARY-" + "".join(secrets.choice(string.ascii_lowercase) for _ in range(16))


def _run(alphabet: str, size: int) -> str:
    return "".join(secrets.choice(alphabet) for _ in range(size))


def _mixed(size: int) -> str:
    body = list(_run(_ALNUM, size))
    body[0], body[1], body[2] = "Q", "q", "7"
    return "".join(body)


def github_token() -> str:
    return "gh" + "p_" + _mixed(36)


def aws_key_id() -> str:
    return "AK" + "IA" + _run(_UPPER_DIGITS, 16)


def storage_account_key() -> str:
    """An Azure storage account-key assignment; returns (labelled text)."""
    return "Account" + "Key=" + _mixed(86) + "=="


def card_number() -> str:
    """A Luhn-valid 16-digit Visa-shaped number, random every call."""
    digits = [4] + [secrets.randbelow(10) for _ in range(14)]
    total = 0
    for index, digit in enumerate(reversed(digits)):
        value = digit * 2 if index % 2 == 0 else digit
        total += value - 9 if value > 9 else value
    digits.append((10 - total % 10) % 10)
    return "".join(map(str, digits))


def retention(*, opt_in: bool = True) -> PolicyState:
    return load_policy(
        {
            "policy_version": "v1",
            "rules": [
                {
                    "data_class": "telemetry_event",
                    "min_retention_days": 0,
                    "max_retention_days": 30,
                },
                {
                    "data_class": "interaction_content",
                    "min_retention_days": 0,
                    "max_retention_days": 90,
                },
            ],
            "retain_prompt_response_bodies": opt_in,
        }
    )


def local_wrapper(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> LocalFileKeyWrapper:
    monkeypatch.setenv("NS_ENV", "local")
    return LocalFileKeyWrapper(tmp_path / "interaction-kek.bin")


def make_store(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, wrapper: Any = None, opt_in: bool = True
) -> InMemoryInteractionStore:
    return InMemoryInteractionStore(
        wrapper if wrapper is not None else local_wrapper(tmp_path, monkeypatch),
        kek_uri=KEK_URI,
        policy=retention(opt_in=opt_in),
    )


def target(**overrides: Any) -> CaptureTarget:
    values: dict[str, Any] = {
        "policy_id": "support-capture",
        "policy_version": 3,
        "domain_id": DOMAIN,
        "source_id": SOURCE,
        "detector_set_version": DEFAULT_SET_VERSION,
        "retention_days": 30,
        "max_per_minute": 600,
    }
    values.update(overrides)
    return CaptureTarget(**values)


def event(**overrides: Any) -> CaptureEvent:
    values: dict[str, Any] = {
        "cloud": "commercial",
        "customer_id": CUSTOMER,
        "domain_id": DOMAIN,
        "source_id": SOURCE,
        "event_id": "evt-" + uuid.uuid4().hex[:12],
        "correlation_id": "corr-" + uuid.uuid4().hex[:12],
        "occurred_at": "2026-11-20T10:15:00Z",
        "trace_id": uuid.uuid4().hex,
        "span_id": uuid.uuid4().hex[:16],
    }
    values.update(overrides)
    return CaptureEvent(**values)


@dataclass
class AuditRecorder:
    """Collects capture audit events; ``fail_on`` makes that operation's write raise."""

    fail_on: frozenset[str] = frozenset()
    events: list[CaptureAuditEvent] = field(default_factory=list)

    async def __call__(self, entry: CaptureAuditEvent) -> None:
        if entry.operation in self.fail_on:
            raise RuntimeError("audit store unavailable")
        self.events.append(entry)


def pipeline(store: InMemoryInteractionStore, **kwargs: Any) -> CapturePipeline:
    return CapturePipeline(store, **kwargs)


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def boom(*_args: Any, **_kwargs: Any) -> Any:
    raise RuntimeError("injected failure")


async def aboom(*_args: Any, **_kwargs: Any) -> Any:
    raise RuntimeError("injected failure")
