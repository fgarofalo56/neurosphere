"""PRP-41 item 1: the secret is strong and never appears in repr or exception text."""

from __future__ import annotations

import re
from typing import Any

import pytest
from neurosphere_core.admin import InMemoryAdminConfigRepository
from neurosphere_core.admin.producers import ProducerAdmin, issue_secret, secret_digest

ACTOR = "commercial:contoso:entra:person:p-" + "0c" * 32


def test_secret_entropy_and_alphabet() -> None:
    issued = issue_secret()
    assert re.fullmatch(r"[A-Za-z0-9_-]{43,128}", issued.secret)
    assert issued.sha256 == secret_digest(issued.secret)
    assert len({issue_secret().secret for _ in range(50)}) == 50


def test_repr_and_str_redact() -> None:
    issued = issue_secret()
    assert issued.secret not in repr(issued)
    assert issued.secret not in str(issued)
    assert issued.sha256 not in repr(issued)


async def test_failed_write_error_text_has_no_secret() -> None:
    repo = InMemoryAdminConfigRepository(cloud="commercial")
    fixed = "S" * 43
    admin = ProducerAdmin(repo, cloud="commercial", token_factory=lambda _n: fixed)
    sources: Any = {"a": "gateway"}
    with pytest.raises(Exception) as exc:
        await admin.create(
            "contoso", "bad id!", cloud="commercial", sources=sources, updated_by=ACTOR
        )
    text = f"{exc.value!s} {exc.value!r}"
    assert fixed not in text and secret_digest(fixed) not in text
