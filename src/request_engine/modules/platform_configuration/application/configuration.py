from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID


class PlatformConfigurationError(Exception):
    pass


class PlatformConfigurationForbidden(PlatformConfigurationError):
    pass


class PlatformConfigurationNotFound(PlatformConfigurationError):
    pass


class PlatformConfigurationConflict(PlatformConfigurationError):
    pass


class PlatformConfigurationRevisionConflict(PlatformConfigurationError):
    pass


class PlatformConfigurationInvalid(PlatformConfigurationError):
    pass


@dataclass(frozen=True, slots=True)
class ConfigurationRevision:
    configuration_revision_id: UUID
    configuration_kind: str
    provider_kind: str
    revision: int
    configuration: dict[str, Any]
    secret_binding_id: UUID | None
    state: str
    created_by_principal_id: UUID
    created_at: datetime
    validated_at: datetime | None
    activated_at: datetime | None
    disabled_at: datetime | None


@dataclass(frozen=True, slots=True)
class SecretBindingMetadata:
    binding_id: UUID
    purpose: str
    backend: str
    backend_version: int
    status: str
    revision: int
    created_at: datetime
    rotated_at: datetime | None
    revoked_at: datetime | None


@dataclass(frozen=True, slots=True)
class StageConfiguration:
    configuration_kind: str
    provider_kind: str
    configuration: dict[str, Any]
    secret_binding_id: UUID | None
    idempotency_key: str


@dataclass(frozen=True, slots=True)
class ValidateConfiguration:
    configuration_kind: str
    revision: int
    expected_binding_revision: int | None
    expected_backend_version: int | None
    idempotency_key: str


@dataclass(frozen=True, slots=True)
class ActivateConfiguration:
    configuration_kind: str
    revision: int
    expected_active_revision: int | None
    idempotency_key: str


@dataclass(frozen=True, slots=True)
class DisableConfiguration:
    configuration_kind: str
    revision: int
    idempotency_key: str


@dataclass(frozen=True, slots=True)
class ConfigurationMutationResult:
    configuration_revision_id: UUID
    revision: int
    state: str
