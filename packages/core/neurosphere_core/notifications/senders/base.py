"""Shared sender plumbing: secret port, credential reads and egress-to-outcome mapping."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import datetime
from typing import Final, Protocol

from neurosphere_contracts.admin.v1.credential_reference import CredentialReference
from neurosphere_contracts.admin.v1.system_setting import NotificationsSetting
from neurosphere_contracts.notifications.v1.notification_channel import NotificationChannel
from pydantic import SecretStr

from neurosphere_core.notifications.egress import EgressGuard, EgressResponse
from neurosphere_core.notifications.ports import SendOutcome

__all__ = ["CREDENTIAL_UNAVAILABLE", "SecretReader", "SenderBase"]

CREDENTIAL_UNAVAILABLE: Final = "credential_unavailable"


class SecretReader(Protocol):
    """Same shape as the workers' Key Vault reader (``connector_config.keyvault``)."""

    async def read(self, reference: CredentialReference) -> SecretStr: ...


def outcome_from(response: EgressResponse) -> SendOutcome:
    if response.ok:
        return SendOutcome(status_code=response.status_code, reason_code=None, retryable=False)
    return SendOutcome(
        status_code=response.status_code,
        reason_code=response.reason_code,
        retryable=response.retryable,
    )


class SenderBase:
    def __init__(
        self,
        guard: EgressGuard,
        secrets: SecretReader,
        *,
        setting: NotificationsSetting,
        deployment_cloud: str,
        ns_env: str,
        clock: Callable[[], datetime],
    ) -> None:
        self._guard = guard
        self._secrets = secrets
        self._setting = setting
        self._cloud = deployment_cloud
        self._ns_env = ns_env
        self._clock = clock

    async def _secret(self, reference: CredentialReference) -> str | None:
        """The secret value, or ``None`` on any failure (the exception text is never kept)."""
        try:
            return (await self._secrets.read(reference)).get_secret_value()
        except Exception:
            return None

    @staticmethod
    def _unavailable() -> SendOutcome:
        return SendOutcome(status_code=None, reason_code=CREDENTIAL_UNAVAILABLE, retryable=True)

    @staticmethod
    def _refused(reason: str) -> SendOutcome:
        return SendOutcome(status_code=None, reason_code=reason, retryable=False)

    async def _post(
        self,
        channel: NotificationChannel,
        url: str,
        body: bytes,
        headers: Mapping[str, str],
    ) -> SendOutcome:
        response = await self._guard.post(
            channel,
            url,
            body,
            headers,
            setting=self._setting,
            deployment_cloud=self._cloud,
            ns_env=self._ns_env,
        )
        return outcome_from(response)
