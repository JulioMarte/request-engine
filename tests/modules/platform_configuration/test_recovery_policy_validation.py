from datetime import UTC, datetime
from typing import cast
from uuid import uuid4

import pytest

from request_engine.modules.platform_configuration.application.configuration import (
    ConfigurationMutationResult,
    ConfigurationRevision,
    PlatformConfigurationProviderInvalid,
    ValidateConfiguration,
)
from request_engine.modules.platform_configuration.application.provider_secrets import (
    ProviderSecretResolver,
)
from request_engine.modules.platform_configuration.application.provider_validation import (
    PlatformProviderValidationService,
)
from request_engine.modules.platform_configuration.application.recovery_policy import (
    recovery_policy_preset_payload,
)
from request_engine.modules.platform_configuration.application.smtp import SmtpConfigurationValidator
from request_engine.platform.security.platform_context import PlatformActorContext


class _Reader:
    def __init__(self, candidate: ConfigurationRevision) -> None:
        self.candidate = candidate

    async def get(
        self,
        actor: PlatformActorContext,
        *,
        configuration_kind: str,
        revision: int,
        capability_key: str,
    ) -> ConfigurationRevision:
        del actor, configuration_kind, revision, capability_key
        return self.candidate


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


def _candidate(configuration: dict[str, object]) -> ConfigurationRevision:
    return ConfigurationRevision(
        configuration_revision_id=uuid4(),
        configuration_kind="operations.recovery_policy",
        provider_kind="coolify-postgres-openbao",
        revision=4,
        configuration=configuration,
        secret_binding_id=None,
        state="draft",
        created_by_principal_id=uuid4(),
        created_at=datetime.now(UTC),
        validated_at=None,
        activated_at=None,
        disabled_at=None,
    )


@pytest.mark.asyncio
async def test_recovery_policy_validation_commits_without_secret_fence() -> None:
    commands = _Commands()
    service = PlatformProviderValidationService(
        reader=_Reader(_candidate(recovery_policy_preset_payload())),
        commands=commands,
        secret_resolver=cast(ProviderSecretResolver, object()),
        secret_store=None,
        smtp_validator=cast(SmtpConfigurationValidator, object()),
    )

    result = await service.validate(
        cast(PlatformActorContext, object()),
        configuration_kind="operations.recovery_policy",
        revision=4,
        idempotency_key="recovery-policy-validation",
    )

    assert result.state == "validated"
    assert commands.command is not None
    assert commands.command.expected_binding_revision is None
    assert commands.command.expected_backend_version is None


@pytest.mark.asyncio
async def test_recovery_policy_validation_rejects_secret_binding() -> None:
    candidate = _candidate(recovery_policy_preset_payload())
    candidate = ConfigurationRevision(
        configuration_revision_id=candidate.configuration_revision_id,
        configuration_kind=candidate.configuration_kind,
        provider_kind=candidate.provider_kind,
        revision=candidate.revision,
        configuration=candidate.configuration,
        secret_binding_id=uuid4(),
        state=candidate.state,
        created_by_principal_id=candidate.created_by_principal_id,
        created_at=candidate.created_at,
        validated_at=None,
        activated_at=None,
        disabled_at=None,
    )
    service = PlatformProviderValidationService(
        reader=_Reader(candidate),
        commands=_Commands(),
        secret_resolver=cast(ProviderSecretResolver, object()),
        secret_store=None,
        smtp_validator=cast(SmtpConfigurationValidator, object()),
    )

    with pytest.raises(PlatformConfigurationProviderInvalid):
        await service.validate(
            cast(PlatformActorContext, object()),
            configuration_kind="operations.recovery_policy",
            revision=4,
            idempotency_key="recovery-policy-invalid-secret",
        )
