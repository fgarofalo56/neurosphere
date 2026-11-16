"""PRP-51: ``NS_STORE_COSMOS_ACCOUNT`` is a Cosmos account name; URLs and keys are refused."""

from __future__ import annotations

import pytest
from neurosphere_workers.runtime.settings import StoreSettings
from pydantic import ValidationError


def test_a_valid_account_name_is_accepted(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NS_STORE_COSMOS_ACCOUNT", "ns-prod-cosmos1")
    assert StoreSettings().cosmos_account == "ns-prod-cosmos1"


def test_unset_and_blank_are_none(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("NS_STORE_COSMOS_ACCOUNT", raising=False)
    assert StoreSettings().cosmos_account is None
    monkeypatch.setenv("NS_STORE_COSMOS_ACCOUNT", "  ")
    assert StoreSettings().cosmos_account is None


@pytest.mark.parametrize(
    "value",
    [
        "https://acct.documents.azure.com:443/",
        "AccountEndpoint=https://x;AccountKey=abc==",
        "Upper",
        "q1",
        "-leading",
        "trailing-",
        "x" * 45,
    ],
)
def test_a_url_or_key_is_refused_without_echo(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    monkeypatch.setenv("NS_STORE_COSMOS_ACCOUNT", value)
    with pytest.raises(ValidationError) as refused:
        StoreSettings()
    assert value not in str(refused.value)
