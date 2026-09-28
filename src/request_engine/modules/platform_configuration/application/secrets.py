from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from request_engine.modules.platform_configuration.application.configuration import (
    PlatformConfigurationError,
)
from request_engine.platform.security.platform_context import PlatformActorContext


class PlatformSecretUnavailable(PlatformConfigurationError):
    pass


class PlatformSecretConflict(PlatformConfigurationError):
    pass


class PlatformSecretNotFound(PlatformConfigurationError):
    pass


class PlatformSecretReconciliationRequired(PlatformConfigurationError):
    pass


@dataclass(frozen=True, slots=True)
class SecretMutationOperation:
    operation_id: UUID
    operation_kind: str
    binding_id: UUID | None
    secret_id: UUID
    purpose: str
    backend: str
    expected_binding_revision: int | None
    expected_backend_version: int | None
    applied_backend_version: int | None
    state: str
    result_binding_id: UUID | None
    result_binding_revision: int | None
    result_binding_status: str | None


@dataclass(frozen=True, slots=True)
class CreatePlatformSecret:
    purpose: str
    backend: str
    value: str
    idempotency_key: str


@dataclass(frozen=True, slots=True)
class RotatePlatformSecretIntent:
    binding_id: UUID
    expected_revision: int
    expected_backend_version: int
    idempotency_key: str


@dataclass(frozen=True, slots=True)
class RotatePlatformSecret(RotatePlatformSecretIntent):
    value: str


@dataclass(frozen=True, slots=True)
class RevokePlatformSecret:
    binding_id: UUID
    expected_revision: int
    expected_backend_version: int
    idempotency_key: str


@dataclass(frozen=True, slots=True)
class SecretMutationResult:
    binding_id: UUID
    revision: int
    backend_version: int
    status: str


class PlatformSecretMutationStore(Protocol):
    async def prepare_create(
        self,
        actor: PlatformActorContext,
        command: CreatePlatformSecret,
    ) -> SecretMutationOperation: ...

    async def prepare_rotate(
        self,
        actor: PlatformActorContext,
        command: RotatePlatformSecretIntent,
    ) -> SecretMutationOperation: ...

    async def prepare_revoke(
        self,
        actor: PlatformActorContext,
        command: RevokePlatformSecret,
    ) -> SecretMutationOperation: ...

    async def mark_backend_applied(
        self,
        actor: PlatformActorContext,
        operation_id: UUID,
        backend_version: int,
    ) -> SecretMutationOperation: ...

    async def commit(
        self,
        actor: PlatformActorContext,
        operation_id: UUID,
    ) -> SecretMutationOperation: ...
