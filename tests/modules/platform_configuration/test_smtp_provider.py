from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import cast
from uuid import UUID, uuid4

import pytest

from request_engine.modules.platform_configuration.application.configuration import (
    ConfigurationMutationResult,
    ConfigurationRevision,
    ValidateConfiguration,
)
from request_engine.modules.platform_configuration.application.provider_validation import (
    PlatformProviderValidationService,
)
from request_engine.modules.platform_configuration.application.smtp import (
    ProviderValidationResult,
    ProviderValidationStatus,
    SmtpConfiguration,
    parse_smtp_configuration,
)
from request_engine.platform.secrets.platform_store import PlatformSecretMetadata
from request_engine.platform.security.platform_context import PlatformActorContext


def _revision(*, username: str | None, binding_id: UUID | None) -> ConfigurationRevision:
    configuration: dict[str, object] = {
        "host": "smtp.example.test",
        "port": 587,
        "sender": "noreply@example.test",
        "security": "starttls",
    }
    if username is not None:
        configuration["username"] = username
    return ConfigurationRevision(
        configuration_revision_id=uuid4(),
        configuration_kind="email.delivery",
        provider_kind="smtp",
        revision=3,
        configuration=configuration,
        secret_binding_id=binding_id,
        state="draft",
        created_by_principal_id=uuid4(),
        created_at=datetime.now(UTC),
        validated_at=None,
        activated_at=None,
        disabled_at=None,
    )


class _CandidateReader:
    def __init__(self, revision: ConfigurationRevision) -> None:
        self.revision = revision
        self.capability: str | None = None

    async def get(
        self,
        actor: PlatformActorContext,
        *,
        configuration_kind: str,
        revision: int,
        capability_key: str,
    ) -> ConfigurationRevision:
        del actor, configuration_kind, revision
        self.capability = capability_key
        return self.revision


class _Commands:
    def __init__(self) -> None:
        self.command: ValidateConfiguration | None = None

    async def validate(
        self,
        actor: PlatformActorContext,
        command: ValidateConfiguration,
    ) -> ConfigurationMutationResult:
        del actor
        self.command = command
        return ConfigurationMutationResult(uuid4(), command.revision, "validated")


@dataclass
class _SecretReference:
    secret_id: UUID
    purpose: str = "email.smtp.password"
    backend: str = "openbao"
    backend_version: int = 9
    status: str = "active"
    revision: int = 4


class _SecretResolver:
    def __init__(self, reference: _SecretReference) -> None:
        self.reference = reference
        self.capability: str | None = None

    async def resolve(
        self,
        actor: PlatformActorContext,
        *,
        binding_id: UUID,
        capability_key: str,
    ) -> _SecretReference:
        del actor, binding_id
        self.capability = capability_key
        return self.reference


class _SecretStore:
    def __init__(self) -> None:
        self.resolved: UUID | None = None

    async def resolve(self, *, secret_id: UUID) -> str:
        self.resolved = secret_id
        return "governed-password"

    async def write(
        self, *, secret_id: UUID, value: str, expected_version: int | None
    ) -> PlatformSecretMetadata:
        raise AssertionError("write not expected")

    async def metadata(self, *, secret_id: UUID) -> PlatformSecretMetadata:
        raise AssertionError("metadata not expected")

    async def revoke(self, *, secret_id: UUID) -> None:
        raise AssertionError("revoke not expected")


class _Validator:
    def __init__(self) -> None:
        self.password: str | None = None
        self.configuration: SmtpConfiguration | None = None

    async def validate(
        self,
        configuration: SmtpConfiguration,
        *,
        password: str | None,
    ) -> ProviderValidationResult:
        self.configuration = configuration
        self.password = password
        return ProviderValidationResult(ProviderValidationStatus.VALID, "smtp_valid")


def test_smtp_configuration_is_typed_and_rejects_unknown_fields() -> None:
    parsed = parse_smtp_configuration(
        {
            "host": "smtp.example.test",
            "port": 465,
            "sender": "noreply@example.test",
            "security": "tls",
            "timeout_seconds": 8,
        }
    )
    assert parsed.host == "smtp.example.test"
    assert parsed.port == 465
    assert parsed.security.value == "tls"

    with pytest.raises(ValueError):
        parse_smtp_configuration(
            {
                "host": "smtp.example.test",
                "port": 465,
                "sender": "noreply@example.test",
                "security": "tls",
                "password": "must-not-be-here",
            }
        )


@pytest.mark.asyncio
async def test_provider_validation_carries_exact_secret_version_to_commit() -> None:
    binding_id = uuid4()
    candidate = _CandidateReader(_revision(username="smtp-user", binding_id=binding_id))
    commands = _Commands()
    reference = _SecretReference(secret_id=uuid4())
    resolver = _SecretResolver(reference)
    store = _SecretStore()
    validator = _Validator()
    service = PlatformProviderValidationService(
        reader=candidate,
        commands=commands,
        secret_resolver=resolver,
        secret_store=store,
        smtp_validator=validator,
    )

    result = await service.validate(
        cast(PlatformActorContext, object()),
        configuration_kind="email.delivery",
        revision=3,
        idempotency_key="same-request",
    )

    assert result.state == "validated"
    assert candidate.capability == "platform.configuration.validate"
    assert resolver.capability == "platform.configuration.validate"
    assert store.resolved == reference.secret_id
    assert validator.password == "governed-password"
    assert commands.command is not None
    assert commands.command.expected_binding_revision == 4
    assert commands.command.expected_backend_version == 9


@pytest.mark.asyncio
async def test_provider_validation_without_auth_has_no_secret_precondition() -> None:
    candidate = _CandidateReader(_revision(username=None, binding_id=None))
    commands = _Commands()
    validator = _Validator()
    service = PlatformProviderValidationService(
        reader=candidate,
        commands=commands,
        secret_resolver=_SecretResolver(_SecretReference(secret_id=uuid4())),
        secret_store=None,
        smtp_validator=validator,
    )

    await service.validate(
        cast(PlatformActorContext, object()),
        configuration_kind="email.delivery",
        revision=3,
        idempotency_key="no-auth",
    )

    assert validator.password is None
    assert commands.command is not None
    assert commands.command.expected_binding_revision is None
    assert commands.command.expected_backend_version is None
