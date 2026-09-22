from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class ResolvedWebhookConfiguration:
    base_url: str
    auth_header_name: str | None
    auth_header_value: str | None
    timeout_seconds: float
    configuration_revision: int
    secret_binding_revision: int | None
    secret_backend_version: int | None


class ActiveWebhookConfigurationResolver(Protocol):
    async def resolve_webhook(
        self,
        *,
        revision: int | None = None,
        force_refresh: bool = False,
    ) -> ResolvedWebhookConfiguration | None: ...
